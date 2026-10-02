"""Mise meal state and conducting logic.

No MCP code in here, so everything is easy to test. Times are integer minutes
since midnight. One Meal = the dinner being cooked right now. One Profile =
what Mise has learned about how fast this cook really is (kept across meals).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from dishes import build_menu
from scheduler import Kitchen, plan as make_plan

STATE_FILE = Path(__file__).with_name("state.json")


# ---------------------------------------------------------------- clock helpers
def clock24(m):
    h, mm = divmod(m % 1440, 60)
    return f"{h:02d}:{mm:02d}"


def clock12(m):
    h, mm = divmod(m % 1440, 60)
    return f"{h % 12 or 12}:{mm:02d} {'AM' if h < 12 else 'PM'}"


_TIME = re.compile(r"(\d{1,2})(?::?(\d{2}))?\s*(am|pm)?")


def _split(text):
    m = _TIME.fullmatch(str(text).strip().lower().replace(".", ""))
    if not m:
        raise ValueError(f"I couldn't read the time '{text}'. Try 20:30 or 8:30 pm.")
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if mi > 59 or (ap and not 1 <= h <= 12) or (not ap and h > 23):
        raise ValueError(f"'{text}' isn't a valid time. Try 20:30 or 8:30 pm.")
    return h, mi, ap


def parse_clock(text):
    """Exact time of day: 24-hour ('19:30') or with am/pm ('7:30 pm')."""
    h, mi, ap = _split(text)
    if ap:
        h = h % 12 + (12 if ap == "pm" else 0)
    return h * 60 + mi


def resolve_time(text, now):
    """A time the cook means from now on: '8:30' at 19:00 means 20:30."""
    h, mi, ap = _split(text)
    if ap or h >= 13 or h == 0:
        return parse_clock(text)
    base = (h % 12) * 60 + mi
    for cand in (base, base + 720):
        if cand > now:
            return cand
    return base + 720


# --------------------------------------------------------------------- learning
@dataclass
class Profile:
    speed: float = 1.0     # >1 means this cook takes longer than the recipe says
    samples: int = 0

    def learn(self, ratio):
        """Blend one observed (actual / recipe) ratio into the running estimate."""
        ratio = min(max(ratio, 0.5), 2.0)
        self.speed = round(min(max(0.7 * self.speed + 0.3 * ratio, 0.5), 2.0), 3)
        self.samples += 1


# ------------------------------------------------------------------------- meal
def _needs(t):
    if t.hands and t.burner:
        return "your hands and a burner"
    if t.hands:
        return "your hands"
    if t.burner:
        return "a burner, no attention needed"
    return "just waiting"


def _row(t, start, end, status):
    return {"id": t.id, "dish": t.dish, "name": t.name, "status": status,
            "minutes": t.minutes, "hands": t.hands, "needs": _needs(t),
            "start": clock24(start), "end": clock24(end),
            "start_12": clock12(start), "end_12": clock12(end)}


@dataclass
class Meal:
    dishes: list
    serve_at: int
    burners: int = 2
    speed: float = 1.0
    started: dict = field(default_factory=dict)   # task id -> minute it started
    done: list = field(default_factory=list)

    def _base(self):
        return {t.id: t for t in build_menu(self.dishes)}

    def _tasks(self):
        """Recipe steps, with hands-on steps stretched/shrunk by learned speed."""
        return [replace(t, minutes=max(1, round(t.minutes * self.speed)) if t.hands else t.minutes)
                for t in build_menu(self.dishes)]

    def finished(self):
        return len(self.done) >= len(self._base())

    def plan(self, now):
        tasks = self._tasks()
        by_id = {t.id: t for t in tasks}
        running = {tid: max(1, by_id[tid].minutes - (now - s))
                   for tid, s in self.started.items() if tid not in self.done}
        return make_plan(tasks, self.serve_at, Kitchen(burners=self.burners),
                         now=now, done=set(self.done), running=running)

    # ---- things that happen in the kitchen
    def start(self, tid, now):
        by_id = self._base()
        if tid not in by_id:
            raise ValueError(f"I don't have a step called '{tid}'.")
        t = by_id[tid]
        if tid in self.done:
            raise ValueError(f"'{t.name}' is already done.")
        if tid in self.started:
            raise ValueError(f"'{t.name}' is already in progress.")
        unmet = [by_id[d].name for d in t.after if d not in self.done]
        if unmet:
            raise ValueError("Finish first: " + ", ".join(unmet) + ".")
        busy = [by_id[i] for i in self.started if i not in self.done]
        if t.hands and any(b.hands for b in busy):
            doing = next(b for b in busy if b.hands)
            raise ValueError(f"You're still busy with '{doing.name}'.")
        if t.burner and sum(b.burner for b in busy) >= self.burners:
            raise ValueError("All burners are in use right now.")
        self.started[tid] = now
        return t

    def finish(self, tid, now):
        """Returns observed (actual / recipe) ratio for hands-on steps, else None."""
        by_id = self._base()
        if tid not in by_id:
            raise ValueError(f"I don't have a step called '{tid}'.")
        t = by_id[tid]
        if tid in self.done:
            raise ValueError(f"'{t.name}' is already done.")
        ratio = None
        if tid in self.started:
            if t.hands:
                ratio = max(now - self.started[tid], 1) / t.minutes
        else:
            unmet = [by_id[d].name for d in t.after if d not in self.done]
            if unmet:
                raise ValueError("Finish first: " + ", ".join(unmet) + ".")
        self.done.append(tid)
        self.started.pop(tid, None)
        return ratio

    def delay_serve(self, minutes):
        self.serve_at += minutes

    def redo(self, tid):
        by_id = self._base()
        if tid not in by_id:
            raise ValueError(f"I don't have a step called '{tid}'.")
        t = by_id[tid]
        if tid not in self.started and tid not in self.done:
            raise ValueError(f"'{t.name}' hasn't been started, so there's nothing to redo.")
        blockers = [x for x in by_id.values()
                    if tid in x.after and (x.id in self.started or x.id in self.done)]
        if blockers:
            raise ValueError(f"Can't redo '{t.name}': '{blockers[0].name}' already depends on it.")
        self.started.pop(tid, None)
        if tid in self.done:
            self.done.remove(tid)
        return t

    def drop_dish(self, dish):
        if dish not in self.dishes:
            raise ValueError(f"'{dish}' isn't on tonight's menu.")
        ids = {t.id for t in self._base().values() if t.dish == dish}
        if ids & (set(self.started) | set(self.done)):
            raise ValueError(f"You've already started {dish}, so I can't drop it.")
        self.dishes = [d for d in self.dishes if d != dish]

    # ---- what the cook should do now
    def status(self, now, horizon=10):
        p = self.plan(now)
        tasks = {t.id: t for t in self._tasks()}
        timeline = [{"id": i, "dish": tasks[i].dish, "name": tasks[i].name, "status": "done"}
                    for i in self.done if i in tasks]
        running, due, up_next, nxt = [], [], [], None
        for s in p.slots:
            t = tasks[s.task.id]
            if t.id in self.started:
                row = _row(t, s.start, s.end, "running")
                running.append(row)
            elif s.start <= now:
                row = _row(t, s.start, s.end, "due")
                due.append(row)
            elif s.start <= now + horizon:
                row = _row(t, s.start, s.end, "up_next")
                up_next.append(row)
                nxt = nxt or row
            else:
                row = _row(t, s.start, s.end, "later")
                nxt = nxt or row
            timeline.append(row)
        due = [r for r in due if r["hands"]] + [r for r in due if not r["hands"]]
        return {"ok": True, "now": clock24(now), "serve_at": clock24(self.serve_at),
                "serve_at_12": clock12(self.serve_at),
                "projected_serve": clock24(p.projected_serve),
                "projected_12": clock12(p.projected_serve),
                "on_track": p.feasible, "late_by": p.late_by,
                "finished": self.finished(), "speed_factor": self.speed,
                "running": running, "due": due, "up_next": up_next, "next": nxt,
                "timeline": timeline}


def narrate(s):
    """Short, speakable guidance for a voice assistant to read out."""
    if s["finished"]:
        return "Everything is done. Enjoy your meal!"
    parts = []
    if s["due"]:
        parts.append(f"Now: {s['due'][0]['name']}.")
        if len(s["due"]) > 1:
            parts.append("Also start " + " and ".join(r["name"] for r in s["due"][1:]) + ".")
    elif s["running"]:
        r = s["running"][0]
        parts.append(f"You're set for now. {r['name']} is in progress until {r['end_12']}.")
    else:
        parts.append("Nothing to do right now.")
    if s["next"] and not s["due"]:
        parts.append(f"Next, at {s['next']['start_12']}: {s['next']['name']}.")
    if not s["on_track"]:
        parts.append(f"Heads up: you're about {s['late_by']} minutes behind, "
                     f"so everything will be ready around {s['projected_12']}.")
    return " ".join(parts)


# ------------------------------------------------------------------ persistence
def save(meal, profile, path=STATE_FILE):
    Path(path).write_text(json.dumps(
        {"meal": asdict(meal) if meal else None, "profile": asdict(profile)}, indent=2),
        encoding="utf-8")


def load(path=STATE_FILE):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        meal = Meal(**raw["meal"]) if raw.get("meal") else None
        return meal, Profile(**raw.get("profile", {}))
    except (OSError, ValueError, TypeError, KeyError):
        return None, Profile()