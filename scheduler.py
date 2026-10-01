"""Mise scheduler: plans a multi-dish meal backward from serve time.

All times are plain integer minutes (the demo uses minutes since midnight).
The cook has one pair of hands; the kitchen has a limited number of burners.
A task may need the cook's hands, a burner, an oven slot, or none of them
(a passive wait such as resting dough).
"""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Task:
    id: str
    dish: str
    name: str
    minutes: int
    hands: bool = True       # needs the cook's attention the whole time
    burner: bool = False     # occupies a burner the whole time
    oven: bool = False
    after: tuple = ()        # task ids that must FINISH before this starts


@dataclass(frozen=True)
class Kitchen:
    burners: int = 2
    ovens: int = 1
    cooks: int = 1


@dataclass
class Slot:
    task: Task
    start: int
    end: int


@dataclass
class Plan:
    slots: list
    serve_at: int
    feasible: bool
    late_by: int             # minutes past serve_at if infeasible, else 0
    projected_serve: int     # when everything is actually finished


def _tails(tasks, preds):
    """Longest chain (in minutes) from each task to the end of its graph."""
    succ = {t.id: [] for t in tasks}
    for tid, ps in preds.items():
        for p in ps:
            succ[p].append(tid)
    dur = {t.id: t.minutes for t in tasks}
    memo = {}

    def tail(tid):
        if tid not in memo:
            memo[tid] = dur[tid] + max((tail(s) for s in succ[tid]), default=0)
        return memo[tid]

    return {t.id: tail(t.id) for t in tasks}


def _fits(t, time, intervals, k):
    if not (t.hands or t.burner or t.oven):
        return True
    end = time + t.minutes
    points = {time} | {s for s, e, _ in intervals if time < s < end}
    for p in points:
        h = b = o = 0
        for s, e, x in intervals:
            if s <= p < e:
                h += x.hands
                b += x.burner
                o += x.oven
        if (t.hands and h + 1 > k.cooks) or (t.burner and b + 1 > k.burners) \
                or (t.oven and o + 1 > k.ovens):
            return False
    return True


def _schedule(tasks, preds, kitchen, start_at, fixed):
    """Greedy list scheduling, longest-chain-first. `fixed` = {id: (start, end)}."""
    by_id = {t.id: t for t in tasks}
    tails = _tails(tasks, preds)
    intervals, start, end = [], {}, {}
    for tid, (s, e) in fixed.items():
        start[tid], end[tid] = s, e
        intervals.append((s, e, by_id[tid]))
    todo = [t for t in tasks if t.id not in fixed]
    time = start_at
    while todo:
        ready = [t for t in todo
                 if all(p in end and end[p] <= time for p in preds[t.id])]
        ready.sort(key=lambda t: (-tails[t.id], t.id))
        for t in ready:
            if _fits(t, time, intervals, kitchen):
                start[t.id], end[t.id] = time, time + t.minutes
                intervals.append((time, time + t.minutes, t))
                todo.remove(t)
        if not todo:
            break
        future = [e for e in end.values() if e > time]
        if not future:
            raise ValueError("Impossible schedule (dependency cycle?)")
        time = min(future)
    return start, end


def plan(tasks, serve_at, kitchen=Kitchen(), now=0, done=(), running=None):
    """Plan (or re-plan) the meal.

    done:    ids of tasks already finished.
    running: {id: minutes_left} for tasks in progress right now.
    Returns a Plan whose slots are in start order. If the meal can't be ready
    by serve_at, feasible=False and the slots show the fastest plan from `now`.
    """
    running = dict(running or {})
    done = set(done)
    all_ids = {t.id for t in tasks}
    for t in tasks:
        for p in t.after:
            if p not in all_ids:
                raise ValueError(f"{t.id} depends on unknown task {p}")
        if t.minutes < 1:
            raise ValueError(f"{t.id} must take at least 1 minute")

    live = [t for t in tasks if t.id not in done]
    live = [replace(t, minutes=max(1, running[t.id])) if t.id in running else t
            for t in live]
    live_ids = {t.id for t in live}
    in_progress = [t for t in live if t.id in running]
    for attr, cap, label in (("hands", kitchen.cooks, "hands-on tasks"),
                             ("burner", kitchen.burners, "burners"),
                             ("oven", kitchen.ovens, "oven slots")):
        used = sum(getattr(t, attr) for t in in_progress)
        if used > cap:
            raise ValueError(
                f"Impossible: {used} {label} in progress but the kitchen only has {cap}.")
    preds = {t.id: {p for p in t.after if p in live_ids} for t in live}
    if not live:
        return Plan([], serve_at, True, 0, now)

    # ---- Backward pass: place everything as late as possible. ----
    window = serve_at - now
    pinned = {tid: rem for tid, rem in running.items() if tid in live_ids}
    result = None
    if all(max(1, rem) <= window for rem in pinned.values()):
        rev_preds = {t.id: set() for t in live}
        for tid, ps in preds.items():
            for p in ps:
                rev_preds[p].add(tid)
        rfixed = {tid: (window - max(1, rem), window) for tid, rem in pinned.items()}
        rs, re_ = _schedule(live, rev_preds, kitchen, 0, rfixed)
        start = {tid: serve_at - re_[tid] for tid in re_}
        end = {tid: serve_at - rs[tid] for tid in rs}
        ok = all(start[t.id] >= now for t in live) and all(
            end[p] <= start[t.id] for t in live for p in preds[t.id])
        if ok:
            result = (start, end)

    # ---- Fallback: fastest possible plan starting now. ----
    if result is None:
        ffixed = {tid: (now, now + max(1, rem)) for tid, rem in pinned.items()}
        result = _schedule(live, preds, kitchen, now, ffixed)

    start, end = result
    by_id = {t.id: t for t in live}
    slots = sorted((Slot(by_id[i], start[i], end[i]) for i in start),
                   key=lambda s: (s.start, s.task.id))
    projected = max(end.values())
    late = max(0, projected - serve_at)
    return Plan(slots, serve_at, late == 0, late, projected)