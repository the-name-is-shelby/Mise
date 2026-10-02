"""Run:  python test_meal.py"""
import math
import tempfile
from pathlib import Path

from meal import Meal, Profile, load, narrate, parse_clock, resolve_time, save

SERVE = 20 * 60 + 30
DISHES = ["dal", "rice", "sabzi", "roti"]


def test_time_parsing():
    assert parse_clock("20:30") == SERVE
    assert parse_clock("8:30 pm") == SERVE
    assert parse_clock("12:15 am") == 15
    assert resolve_time("8:30", 19 * 60) == SERVE          # evening, so PM
    assert resolve_time("8:30", 7 * 60) == 8 * 60 + 30      # morning, so AM
    assert resolve_time("8:30 pm", 7 * 60) == SERVE
    for bad in ("banana", "25:00", "13 pm", "8:75"):
        try:
            parse_clock(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should be rejected")


def simulate(factor, start_before=75):
    """Walk through the whole dinner minute by minute with a cook who takes
    `factor` times the recipe time on hands-on steps. Returns (end_minute, meal, profile)."""
    meal, profile = Meal(dishes=DISHES, serve_at=SERVE), Profile()
    base, actual, now = meal._base(), {}, SERVE - start_before
    while now < SERVE + 240:
        for tid, s in list(meal.started.items()):
            if now - s >= actual[tid]:
                ratio = meal.finish(tid, now)
                if ratio is not None:
                    profile.learn(ratio)
                    meal.speed = profile.speed
        if meal.finished():
            return now, meal, profile
        for row in meal.status(now)["due"]:
            try:
                t = meal.start(row["id"], now)
            except ValueError:
                continue
            actual[t.id] = math.ceil(base[t.id].minutes * factor) if t.hands else t.minutes
        now += 1
    raise AssertionError("dinner never finished")


def test_on_pace_cook_finishes_on_time():
    end, meal, _ = simulate(1.0)
    assert end <= SERVE + 1, f"finished {end - SERVE} min late"


def test_slow_cook_is_learned():
    end, meal, profile = simulate(1.5)
    assert profile.samples >= 5
    assert 1.2 < profile.speed <= 1.6, profile.speed


def test_fast_cook_is_learned():
    _, _, profile = simulate(0.7)
    assert profile.speed < 0.95, profile.speed


def test_hands_conflict_is_rejected():
    meal = Meal(dishes=DISHES, serve_at=SERVE)
    meal.start("rice.wash", SERVE - 60)
    try:
        meal.start("dal.wash", SERVE - 60)
    except ValueError as e:
        assert "busy" in str(e)
    else:
        raise AssertionError("one cook can't wash two things at once")


def test_order_is_enforced():
    meal = Meal(dishes=DISHES, serve_at=SERVE)
    try:
        meal.start("dal.cook", SERVE - 60)
    except ValueError as e:
        assert "Finish first" in str(e)
    else:
        raise AssertionError("dal can't cook before it is washed")


def test_burner_limit():
    meal = Meal(dishes=DISHES, serve_at=SERVE, burners=1)
    for tid in ("rice.wash",):
        meal.start(tid, 0); meal.finish(tid, 3)
    meal.start("rice.cook", 3)
    meal.start("dal.wash", 3); meal.finish("dal.wash", 6)
    try:
        meal.start("dal.cook", 6)
    except ValueError as e:
        assert "burner" in str(e)
    else:
        raise AssertionError("only one burner exists")


def test_late_guests_and_dropping_a_dish():
    meal = Meal(dishes=DISHES, serve_at=SERVE)
    before = meal.status(SERVE - 120)["timeline"][0]["start"]
    meal.delay_serve(20)
    after = meal.status(SERVE - 120)["timeline"][0]["start"]
    assert before != after
    meal.drop_dish("sabzi")
    assert not any(r["dish"] == "sabzi" for r in meal.status(SERVE - 120)["timeline"])


def test_redo_and_drop_rules():
    meal = Meal(dishes=DISHES, serve_at=SERVE)
    meal.start("dal.chop", SERVE - 70); meal.finish("dal.chop", SERVE - 62)
    meal.redo("dal.chop")                       # burnt/spilled: do it again
    assert "dal.chop" not in meal.done
    meal.start("dal.wash", SERVE - 60)
    try:
        meal.drop_dish("dal")
    except ValueError as e:
        assert "already started" in str(e)
    else:
        raise AssertionError("can't drop a dish that's underway")


def test_narration_is_speakable():
    meal = Meal(dishes=DISHES, serve_at=SERVE)
    s = meal.status(SERVE - 200)
    say = narrate(s)
    assert say.startswith("Nothing to do right now.") and "Next, at" in say
    s = meal.status(SERVE - 60)
    assert narrate(s).startswith("Now:") or "Heads up" in narrate(s)


def test_state_survives_restart():
    meal, profile = Meal(dishes=DISHES, serve_at=SERVE), Profile()
    meal.start("rice.wash", 1000)
    profile.learn(1.4)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "state.json"
        save(meal, profile, p)
        m2, p2 = load(p)
    assert m2.started == {"rice.wash": 1000} and m2.dishes == DISHES
    assert p2.speed == profile.speed and p2.samples == 1


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"\nAll {len(tests)} checks passed.")