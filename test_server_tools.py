"""Run:  python test_server_tools.py   (calls the MCP tools directly, no network)"""
import os
import tempfile

_tmp = tempfile.TemporaryDirectory()
os.environ["MISE_STATE_FILE"] = os.path.join(_tmp.name, "state.json")   # never touch real state

import server  # noqa: E402


def test_unknown_dish_and_past_time_give_helpful_errors():
    r = server.plan_meal(["dal", "pizza"], "8:30 pm", now_time="18:30")
    assert r["ok"] is False and "pizza" in r["say"]
    r = server.plan_meal(["dal"], "6:00 pm", now_time="19:00")
    assert r["ok"] is False and "passed" in r["say"]


def test_full_conversation():
    assert "dal" in server.list_dishes()["dishes"]
    assert server.next_action()["ok"] is False or server.MEAL is not None

    r = server.plan_meal(["dal", "rice", "sabzi", "roti"], "8:30 pm", now_time="18:30")
    assert r["ok"] and r["on_track"] and r["serve_at"] == "20:30"
    assert "Planned dal, rice, sabzi, roti for 8:30 PM." in r["say"]

    r = server.next_action(now_time="19:25")
    assert r["due"] and r["due"][0]["id"] == "rice.wash"
    assert r["say"].startswith("Now: Wash the rice")

    r = server.report_event("started", task_id="rice.wash", now_time="19:25")
    assert r["ok"] and r["running"][0]["id"] == "rice.wash"
    r = server.report_event("finished", task_id="rice.wash", now_time="19:30")   # took 5, recipe says 3
    assert r["ok"] and server.PROFILE.speed > 1.0                                  # it learned

    r = server.report_event("started", task_id="dal.cook", now_time="19:31")       # out of order
    assert r["ok"] is False and "Finish first" in r["say"]

    r = server.report_event("delay_serve", minutes=20, now_time="19:32")
    assert r["serve_at"] == "20:50"

    r = server.report_event("drop_dish", dish="sabzi", now_time="19:33")
    assert r["ok"] and not any(x["dish"] == "sabzi" for x in r["timeline"])

    r = server.get_state(now_time="19:34")
    assert r["ok"] and r["timeline"][0]["status"] == "done"


def test_state_is_saved_to_disk():
    meal, profile = server.load(server.STATE_PATH)
    assert meal is not None and meal.dishes == ["dal", "rice", "roti"]
    assert profile.samples >= 1


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("PASS", t.__name__)
    print(f"\nAll {len(tests)} checks passed.")