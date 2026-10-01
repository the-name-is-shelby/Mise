"""Run:  python test_scheduler.py   (no extra packages needed)"""
import random

from dishes import build_menu, load_library
from scheduler import Kitchen, plan

SERVE = 20 * 60 + 30


def check_valid(p, kitchen, now):
    by_end = {s.task.id: s.end for s in p.slots}
    for s in p.slots:
        assert s.start >= now, f"{s.task.id} starts before now"
        assert s.end - s.start == s.task.minutes, f"{s.task.id} wrong length"
        for dep in s.task.after:
            if dep in by_end:
                assert by_end[dep] <= s.start, f"{s.task.id} starts before {dep} ends"
    if p.slots:
        for m in range(min(s.start for s in p.slots), max(s.end for s in p.slots)):
            live = [s.task for s in p.slots if s.start <= m < s.end]
            assert sum(t.hands for t in live) <= kitchen.cooks, f"too many hands at {m}"
            assert sum(t.burner for t in live) <= kitchen.burners, f"too many burners at {m}"
            assert sum(t.oven for t in live) <= kitchen.ovens, f"too many ovens at {m}"


def test_full_menu_is_valid_and_on_time():
    k = Kitchen(burners=2)
    p = plan(build_menu(["dal", "rice", "sabzi", "roti"]), SERVE, k, now=18 * 60)
    check_valid(p, k, 18 * 60)
    assert p.feasible and p.late_by == 0
    assert max(s.end for s in p.slots) == SERVE, "something should finish exactly at serve time"
    assert all(s.end <= SERVE for s in p.slots)


def test_roti_is_last_thing_off_the_stove():
    p = plan(build_menu(["dal", "rice", "sabzi", "roti"]), SERVE, Kitchen(2), now=18 * 60)
    ends = {s.task.id: s.end for s in p.slots}
    assert ends["roti.cook"] == SERVE, "rotis must be fresh: they finish at serve time"


def test_too_late_is_reported_not_hidden():
    k = Kitchen(2)
    p = plan(build_menu(["dal", "rice", "sabzi", "roti"]), SERVE, k, now=SERVE - 30)
    check_valid(p, k, SERVE - 30)
    assert not p.feasible and p.late_by > 0
    assert p.projected_serve == SERVE + p.late_by


def test_guests_late_shifts_plan_later():
    tasks = build_menu(["dal", "rice", "sabzi", "roti"])
    a = plan(tasks, SERVE, Kitchen(2), now=18 * 60)
    b = plan(tasks, SERVE + 20, Kitchen(2), now=18 * 60)
    assert min(s.start for s in b.slots) == min(s.start for s in a.slots) + 20


def test_replan_with_task_in_progress():
    k = Kitchen(2)
    tasks = build_menu(["dal", "rice", "sabzi", "roti"])
    now = 19 * 60 + 30
    p = plan(tasks, SERVE + 20, k, now=now,
             done={"dal.wash", "rice.wash"}, running={"dal.cook": 10})
    check_valid(p, k, now)
    slot = next(s for s in p.slots if s.task.id == "dal.cook")
    assert slot.start == now or slot.end - slot.start == 10
    assert not any(s.task.id in {"dal.wash", "rice.wash"} for s in p.slots)


def test_one_burner_still_valid():
    k = Kitchen(burners=1)
    p = plan(build_menu(["dal", "rice", "sabzi", "roti"]), SERVE, k, now=0)
    check_valid(p, k, 0)


def test_random_cases_never_break_the_rules():
    rng = random.Random(42)
    lib = load_library()
    names = sorted(lib)
    for _ in range(300):
        menu = rng.sample(names, rng.randint(1, 4))
        k = Kitchen(burners=rng.randint(1, 3))
        tasks = build_menu(menu)
        now = rng.randint(0, 200)
        serve = now + rng.randint(10, 150)
        ids = [t.id for t in tasks]
        done = {i for i in ids if rng.random() < 0.15}
        # a task can only be done/running if its prerequisites are done
        done = {i for i in done if all(d in done for d in next(t for t in tasks if t.id == i).after)}
        running, hands, burners = {}, 0, 0
        for t in tasks:
            if t.id not in done and all(d in done for d in t.after) and rng.random() < 0.3:
                if hands + t.hands > k.cooks or burners + t.burner > k.burners:
                    continue  # the cook can't physically be doing this too
                hands += t.hands
                burners += t.burner
                running[t.id] = rng.randint(1, t.minutes)
        p = plan(tasks, serve, k, now=now, done=done, running=running)
        check_valid(p, k, now)
        assert p.feasible == (p.projected_serve <= serve)


def test_impossible_input_is_rejected():
    tasks = build_menu(["dal", "roti"])
    try:
        plan(tasks, SERVE, Kitchen(2), now=0,
             done={"dal.chop", "roti.rest", "roti.dough"},
             running={"dal.wash": 2, "roti.cook": 5})
    except ValueError as e:
        assert "hands-on" in str(e)
    else:
        raise AssertionError("two hands-on tasks at once should be rejected")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"\nAll {len(tests)} checks passed.")