"""Demo clock.

A fake, controllable system time. All scheduling/workflow code reads
get_demo_now() instead of datetime.now(), so 30 days of collections
activity can be replayed in seconds by advancing this clock - each
advance fires every scheduled action due before the new time, in order.
"""

import json
from datetime import datetime, timedelta

from . import config
from .db import get_conn

UNIT_DELTAS = {
    "hour": lambda n: timedelta(hours=n),
    "day": lambda n: timedelta(days=n),
}


def get_demo_clock() -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM demo_clock WHERE id = 1").fetchone()
    return dict(row)


def get_demo_now() -> datetime:
    return datetime.fromisoformat(get_demo_clock()["current_time"])


def set_demo_clock(current_time_iso: str) -> dict:
    with get_conn() as conn:
        conn.execute("UPDATE demo_clock SET current_time = ? WHERE id = 1", (current_time_iso,))
    return get_demo_clock()


def seed_start_time() -> str:
    """The demo's start time, taken from data/seed.json so a reset lands on
    exactly the same clock a fresh seed produces. config.DEMO_CLOCK_START is
    only the fallback for when the seed file has no demo_clock block - having
    reset use it unconditionally meant Reset jumped to a different time than
    seeding did."""
    try:
        with open(config.SEED_PATH) as f:
            return json.load(f)["demo_clock"]["current_time"]
    except (OSError, KeyError, json.JSONDecodeError):
        return config.DEMO_CLOCK_START


def reset_demo_clock() -> dict:
    return set_demo_clock(seed_start_time())


def advance_demo_clock(amount: int, unit: str) -> dict:
    from .scheduler import process_due_actions  # deferred: avoids a circular import

    if unit not in UNIT_DELTAS:
        return {"error": f"unsupported unit '{unit}', expected 'hour' or 'day'"}

    new_now = get_demo_now() + UNIT_DELTAS[unit](amount)
    set_demo_clock(new_now.isoformat())
    fired = process_due_actions(new_now)
    return {"current_time": new_now.isoformat(), "actions_fired": fired}
