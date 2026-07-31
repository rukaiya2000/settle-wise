"""Demo clock controls (md/technical-spec.md "Demo Clock")."""

from fastapi import APIRouter
from pydantic import BaseModel

from .. import demo_clock

router = APIRouter()


class AdvanceRequest(BaseModel):
    amount: int
    unit: str  # "hour" | "day"


class SetRequest(BaseModel):
    current_time: str


@router.get("/api/demo-clock")
def get_demo_clock():
    return demo_clock.get_demo_clock()


@router.post("/api/demo-clock/advance")
def advance_demo_clock(body: AdvanceRequest):
    return demo_clock.advance_demo_clock(body.amount, body.unit)


@router.post("/api/demo-clock/set")
def set_demo_clock(body: SetRequest):
    return demo_clock.set_demo_clock(body.current_time)


@router.post("/api/demo-clock/reset")
def reset_demo_clock():
    """Full demo reset, not just the clock: advancing time mutates borrower
    state via the scheduler, so rewinding the clock alone leaves the next run
    starting from 'paid'/'needs_review' instead of the seeded state."""
    from ..seed import reset_db

    reset_db()
    return demo_clock.get_demo_clock()
