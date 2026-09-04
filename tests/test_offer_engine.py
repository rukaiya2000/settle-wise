"""server/offer_engine.py is the one module the project's whole thesis rests
on: "the agent can't invent anything... every offer... is enforced in code
rather than trusted to the prompt." These tests exist to make that claim
checkable, not just asserted in a README.
"""

import pytest

from server import offer_engine

POLICY = {
    "due_now_percent": 10,
    "min_payment_today_percent": 5,
    "max_discount_percent": 15,
    "cycle_days": 5,
}


# -- payment_targets ---------------------------------------------------------


def test_payment_targets_basic_split():
    t = offer_engine.payment_targets(amount_due=1000, amount_collected=0, policy=POLICY)
    assert t["remaining"] == 1000
    assert t["due_now"] == 100  # 10% of remaining
    assert t["floor"] == 50  # 5% of remaining
    assert t["cycles_to_clear"] == 10


def test_remaining_floored_at_zero_on_overpayment():
    """amount_collected > amount_due (duplicate payment, rounding drift)
    must not make remaining negative - a negative remaining would invert
    the floor and the accept-range for every downstream offer."""
    t = offer_engine.payment_targets(amount_due=500, amount_collected=600, policy=POLICY)
    assert t["remaining"] == 0
    assert t["due_now"] == 0
    assert t["floor"] == 0


def test_payment_targets_missing_policy_field_raises():
    with pytest.raises(ValueError, match="due_now_percent"):
        offer_engine.payment_targets(1000, 0, {"min_payment_today_percent": 5})


# -- payment_schedule ---------------------------------------------------------


def test_payment_schedule_installments_sum_to_remaining():
    sched = offer_engine.payment_schedule(amount_due=1000, amount_collected=0, policy=POLICY, start=None, limit=100)
    assert sum(row["amount"] for row in sched["schedule"]) == pytest.approx(1000, abs=0.02)
    assert sched["more_cycles"] == 0  # limit=100 comfortably covers all 10 cycles


def test_payment_schedule_respects_limit():
    sched = offer_engine.payment_schedule(amount_due=1000, amount_collected=0, policy=POLICY, start=None, limit=3)
    assert len(sched["schedule"]) == 3
    assert sched["more_cycles"] == 7  # 10 total cycles - 3 shown


def test_payment_schedule_terminates_when_due_now_rounds_to_zero():
    """A due_now_percent so small it rounds to 0 must not spin the runaway
    guard for 60 empty entries - it should stop immediately with nothing
    scheduled."""
    tiny_policy = {**POLICY, "due_now_percent": 0.0001}
    sched = offer_engine.payment_schedule(amount_due=10, amount_collected=0, policy=tiny_policy, start=None, limit=100)
    assert sched["schedule"] == []


# -- generate_offer_options: the floor is absolute --------------------------


def test_below_floor_offer_is_empty_and_flagged():
    """The core guardrail: an offer below the floor must come back as an
    empty offer list, not a discounted or partial acceptance - the agent
    has nothing to say yes to, no matter how it's pressured."""
    result = offer_engine.generate_offer_options(amount_due=1000, amount_collected=0, policy=POLICY, borrower_can_pay_today=10)
    assert result["below_floor"] is True
    assert result["offers"] == []


def test_at_floor_offer_is_accepted():
    result = offer_engine.generate_offer_options(amount_due=1000, amount_collected=0, policy=POLICY, borrower_can_pay_today=50)
    assert result["below_floor"] is False
    assert result["offers"] != []


def test_no_amount_named_is_not_treated_as_zero():
    """A borrower saying 'no' isn't an offer of zero - passing 0/None used
    to trip the floor and skip negotiation entirely."""
    for unnamed in (None, 0):
        result = offer_engine.generate_offer_options(amount_due=1000, amount_collected=0, policy=POLICY, borrower_can_pay_today=unnamed)
        assert result["below_floor"] is False
        assert any(o["type"] == "due_now" for o in result["offers"])


def test_offer_above_balance_is_capped_and_flagged():
    """An offer above the outstanding balance can't reach a payment link
    for an inflated figure - it must be capped at what's actually owed."""
    result = offer_engine.generate_offer_options(amount_due=1000, amount_collected=900, policy=POLICY, borrower_can_pay_today=500)
    assert result["exceeds_balance"] is True
    assert result["total_outstanding"] == 100
    # Nothing in the offer list should ever ask for more than what's owed.
    for offer in result["offers"]:
        amount = offer.get("amount") or offer.get("amount_today")
        assert amount <= 100


def test_discount_settlement_never_drops_below_floor():
    """The discount cap is enforced the same way as the floor: a
    discount_settlement offer must never itself fall below the floor."""
    result = offer_engine.generate_offer_options(amount_due=1000, amount_collected=0, policy=POLICY)
    discount_offers = [o for o in result["offers"] if o["type"] == "discount_settlement"]
    for offer in discount_offers:
        assert offer["amount"] >= result["minimum_acceptable_today"]


# -- apply_discount: the agent can't grant more than policy allows ----------


def test_apply_discount_rejects_negative_percent():
    assert offer_engine.apply_discount(1000, -5, POLICY) is None


def test_apply_discount_rejects_above_cap():
    assert offer_engine.apply_discount(1000, POLICY["max_discount_percent"] + 1, POLICY) is None


def test_apply_discount_accepts_valid_percent():
    settled = offer_engine.apply_discount(1000, 10, POLICY)
    assert settled == 900


def test_apply_discount_at_exact_cap_is_allowed():
    settled = offer_engine.apply_discount(1000, POLICY["max_discount_percent"], POLICY)
    assert settled == pytest.approx(1000 * (1 - POLICY["max_discount_percent"] / 100))
