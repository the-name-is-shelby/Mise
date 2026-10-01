"""Loads the dish library from dishes.json into scheduler Tasks."""
import json
from pathlib import Path

from scheduler import Task

_PATH = Path(__file__).with_name("dishes.json")


def load_library(path=_PATH):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        dish: [
            Task(
                id=t["id"], dish=dish, name=t["name"], minutes=t["minutes"],
                hands=t.get("hands", True), burner=t.get("burner", False),
                oven=t.get("oven", False), after=tuple(t.get("after", [])),
            )
            for t in steps
        ]
        for dish, steps in raw.items()
    }


def build_menu(names, library=None):
    library = library or load_library()
    missing = [n for n in names if n not in library]
    if missing:
        raise KeyError(f"Unknown dishes: {missing}. Known: {sorted(library)}")
    return [t for n in names for t in library[n]]