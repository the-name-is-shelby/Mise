"""Mise MCP server: a voice conductor for cooking a whole meal.

Run:  python server.py        (serves http://127.0.0.1:8000/mcp)
"""
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from dishes import build_menu, load_library
from meal import (Meal, Profile, clock12, load, narrate, parse_clock,
                  resolve_time, save)

STATE_PATH = Path(os.environ.get("MISE_STATE_FILE", Path(__file__).with_name("state.json")))

mcp = FastMCP("mise")
MEAL, PROFILE = load(STATE_PATH)


def _now(now_time=""):
    if now_time:
        return parse_clock(now_time)
    n = datetime.now()
    return n.hour * 60 + n.minute


def _reply(now, prefix=""):
    s = MEAL.status(now)
    s["say"] = (prefix + " " + narrate(s)).strip()
    return s


def _no_meal():
    return {"ok": False, "say": "There's no meal planned yet. "
            "Tell me what you're cooking and when to serve it."}


@mcp.tool()
def ping() -> str:
    """Health check."""
    return "mise is alive"


@mcp.tool()
def list_dishes() -> dict[str, Any]:
    """List the dishes Mise knows how to cook."""
    names = sorted(load_library())
    return {"ok": True, "dishes": names, "say": "I can plan: " + ", ".join(names) + "."}


@mcp.tool()
def plan_meal(dishes: list[str], serve_time: str, burners: int = 2,
              now_time: str = "") -> dict[str, Any]:
    """Plan a whole multi-dish meal backward from the time it should be served.

    dishes: dish names from list_dishes, e.g. ["dal", "rice", "sabzi", "roti"].
    serve_time: when to eat, like "8:30 pm" or "20:30".
    burners: how many burners the cook has (default 2).
    now_time: leave empty. Only for testing; sets the current time like "18:30".
    Replaces any meal already in progress.
    """
    global MEAL
    try:
        now = _now(now_time)
        serve = resolve_time(serve_time, now)
        if serve <= now:
            raise ValueError("That serve time has already passed.")
        if not 1 <= burners <= 6:
            raise ValueError("Burners should be between 1 and 6.")
        names = list(dict.fromkeys(d.strip().lower() for d in dishes))
        if not names:
            raise ValueError("Tell me at least one dish to cook.")
        try:
            build_menu(names)
        except KeyError as e:
            raise ValueError(e.args[0])
        new = Meal(dishes=names, serve_at=serve, burners=burners, speed=PROFILE.speed)
        MEAL = new
        save(MEAL, PROFILE, STATE_PATH)
        return _reply(now, f"Planned {', '.join(names)} for {clock12(serve)}.")
    except ValueError as e:
        return {"ok": False, "say": str(e)}


@mcp.tool()
def next_action(now_time: str = "") -> dict[str, Any]:
    """What should the cook do right now, what is cooking, and what is next.

    Call this whenever the cook asks "what's next?". Read the "say" field aloud.
    """
    if MEAL is None:
        return _no_meal()
    return _reply(_now(now_time))


@mcp.tool()
def get_state(now_time: str = "") -> dict[str, Any]:
    """Full timeline of the meal (done, running, due, later) for showing on a card."""
    if MEAL is None:
        return _no_meal()
    return _reply(_now(now_time))


@mcp.tool()
def report_event(event: Literal["started", "finished", "redo", "delay_serve", "drop_dish"],
                 task_id: str = "", minutes: int = 0, dish: str = "",
                 now_time: str = "") -> dict[str, Any]:
    """Tell Mise what just happened in the kitchen, and get the updated plan.

    started: the cook began step task_id (ids come from next_action/get_state).
    finished: the cook finished step task_id.
    redo: step task_id went wrong (burnt, spilled) and must be done again.
    delay_serve: guests are late/early; minutes is positive for later, negative for earlier.
    drop_dish: skip a whole dish (e.g. out of an ingredient); dish is its name.
    """
    global MEAL, PROFILE
    if MEAL is None:
        return _no_meal()
    try:
        now = _now(now_time)
        if event == "started":
            t = MEAL.start(task_id, now)
            prefix = f"Started: {t.name}."
        elif event == "finished":
            name = MEAL._base()[task_id].name if task_id in MEAL._base() else task_id
            ratio = MEAL.finish(task_id, now)
            if ratio is not None:
                PROFILE.learn(ratio)
                MEAL.speed = PROFILE.speed
            prefix = f"Done: {name}."
        elif event == "redo":
            t = MEAL.redo(task_id)
            prefix = f"Okay, we'll redo: {t.name}."
        elif event == "delay_serve":
            if not minutes:
                raise ValueError("How many minutes later or earlier?")
            MEAL.delay_serve(minutes)
            prefix = f"Okay, serving at {clock12(MEAL.serve_at)} instead."
        else:
            MEAL.drop_dish(dish.strip().lower())
            prefix = f"Dropped {dish}."
        save(MEAL, PROFILE, STATE_PATH)
        return _reply(now, prefix)
    except ValueError as e:
        return {"ok": False, "say": str(e)}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")