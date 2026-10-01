"""Prints Mise plans so you can read them like a cooking timeline.
Run:  python demo.py
"""
from dishes import build_menu
from scheduler import Kitchen, plan

MENU = ["dal", "rice", "sabzi", "roti"]
KITCHEN = Kitchen(burners=2)


def clock(m):
    h, mm = divmod(m % 1440, 60)
    return f"{h:02d}:{mm:02d}"


def show(title, p):
    print(f"\n=== {title} ===")
    for s in p.slots:
        tag = ("H" if s.task.hands else "-") + ("B" if s.task.burner else "-")
        print(f"{clock(s.start)}-{clock(s.end)}  [{tag}]  {s.task.name}  ({s.task.dish})")
    if p.feasible:
        print(f"OK: everything ready by {clock(p.projected_serve)} (serve {clock(p.serve_at)})")
    else:
        print(f"TOO LATE: earliest finish {clock(p.projected_serve)}, "
              f"{p.late_by} min after the {clock(p.serve_at)} target")


tasks = build_menu(MENU)
serve = 20 * 60 + 30

show("A) Dinner at 20:30, planning at 18:30",
     plan(tasks, serve, KITCHEN, now=18 * 60 + 30))

show("B) Same dinner, but it is already 19:45",
     plan(tasks, serve, KITCHEN, now=19 * 60 + 45))

show("C) 19:30, dal wash done and dal is cooking (10 min left); guests 20 min late",
     plan(tasks, serve + 20, KITCHEN, now=19 * 60 + 30,
          done={"dal.wash", "rice.wash"}, running={"dal.cook": 10}))