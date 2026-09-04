"""Deterministic offer generation - what the agent tool surface may offer.

Repayment runs on a cycle: `due_now_percent` of the balance is due now, and
the same amount again every `cycle_days` until the balance clears - 10% every
5 days settles it in 50 days. The agent never asks for more than one cycle's
worth at a time.

Below the cycle amount sits a hard floor (`min_payment_today_percent` of the
balance). It applies to what they commit to *for this cycle*, and is enforced
here in code rather than left to the prompt, so a persistent borrower cannot
talk the agent under it. Anything lower comes back with an empty offer list
and a flag to escalate.
"""

import math
from datetime import timedelta


def _require_policy_fields(policy: dict, *fields: str):
    """Fail with a clear message naming the missing field, instead of a bare
    KeyError from direct indexing further down."""
    missing = [f for f in fields if policy.get(f) is None]
    if missing:
        raise ValueError(f"policy is missing required field(s): {', '.join(missing)}")


def payment_targets(amount_due: float, amount_collected: float, policy: dict) -> dict:
    """The numbers every offer is derived from."""
    _require_policy_fields(policy, "due_now_percent", "min_payment_today_percent")
    # Floored at 0 - amount_collected can exceed amount_due (a duplicate
    # payment, manual overpayment, rounding drift across partial payments),
    # and a negative "remaining" would otherwise poison every figure derived
    # from it (negative due_now/floor, a backwards accept-range for the
    # agent).
    remaining = max(0.0, round(amount_due - amount_collected, 2))
    due_now = round(remaining * (policy["due_now_percent"] / 100), 2)
    return {
        "remaining": remaining,
        "due_now": due_now,
        "floor": round(remaining * (policy["min_payment_today_percent"] / 100), 2),
        "cycle_days": int(policy.get("cycle_days") or 5),
        # How many cycles at this rate clear the balance.
        "cycles_to_clear": max(1, int(-(-remaining // due_now))) if due_now > 0 else 1,
    }


def _schedule(due_now: float, remaining: float, cycle_days: int, start) -> list[dict]:
    """The recurring plan: due_now every cycle_days until nothing is left."""
    plan, owed, when, n = [], remaining, start, 0
    while owed > 0.005 and n < 60:  # 60 = runaway guard, not a policy limit
        amount = round(min(due_now, owed), 2)
        if amount <= 0:
            # due_now can't cover any of what's left (e.g. a due_now_percent
            # so small it rounds to zero) - stop instead of burning the
            # runaway guard on 60 zero-amount entries that never converge.
            break
        plan.append({"amount": amount, "on": when.strftime("%Y-%m-%d") if when else None})
        owed = round(owed - amount, 2)
        if when:
            when = when + timedelta(days=cycle_days)
        n += 1
    return plan


def payment_schedule(amount_due: float, amount_collected: float, policy: dict, start, limit: int = 8) -> dict:
    """Upcoming due_now installments for the dashboard, sized/spaced per this
    debt's effective policy, anchored on `start` (the demo clock's current
    time) rather than a fixed calendar date - so it always reads as "what's
    next from today", never a stale schedule if payments arrived out of step
    with a projected date. `limit` caps the list actually returned; the true
    remaining count is still reported via cycles_to_clear/more_cycles."""
    t = payment_targets(amount_due, amount_collected, policy)
    full = _schedule(t["due_now"], t["remaining"], t["cycle_days"], start)
    return {
        "due_now": t["due_now"],
        "minimum_acceptable_today": t["floor"],
        "cycle_days": t["cycle_days"],
        "cycles_to_clear": t["cycles_to_clear"],
        "schedule": full[:limit],
        "more_cycles": max(0, len(full) - limit),
    }


def generate_offer_options(
    amount_due: float,
    amount_collected: float,
    policy: dict,
    borrower_can_pay_today: float | None = None,
    has_future_income_date: bool = False,
    today=None,
) -> dict:
    _require_policy_fields(policy, "max_discount_percent")
    t = payment_targets(amount_due, amount_collected, policy)
    remaining, due_now, floor, cycle_days = t["remaining"], t["due_now"], t["floor"], t["cycle_days"]

    # A borrower declining the full amount is NOT an offer of zero. The agent
    # was passing 0 when they simply said "no", which tripped the floor and
    # skipped negotiation entirely. Treat 0/None as "no figure named yet" and
    # ask them; a genuine refusal is handled by mark_needs_review, not here.
    named_amount = borrower_can_pay_today is not None and borrower_can_pay_today > 0
    # An offer above the entire outstanding balance isn't a real offer to
    # act on - cap what gets confirmed/quoted at what's actually owed rather
    # than pass an inflated (possibly malformed) figure through to a
    # payment link.
    exceeds_balance = named_amount and borrower_can_pay_today > remaining
    capped_amount = min(borrower_can_pay_today, remaining) if named_amount else borrower_can_pay_today
    below_floor = named_amount and capped_amount < floor

    offers = []
    if not below_floor:
        offers.append(
            {
                "type": "due_now",
                "amount": due_now,
                "note": "due today - ask for this. Payment is expected today, not spread over weeks.",
            }
        )
        if named_amount and capped_amount < due_now:
            # At or above the floor but short of the cycle amount: take it and
            # carry the shortfall into this cycle.
            amount_today = round(capped_amount, 2)
            offers.append(
                {
                    "type": "partial",
                    "amount_today": amount_today,
                    "short_this_cycle": round(due_now - amount_today, 2),
                }
            )
        max_discount_amount = round(due_now * (policy["max_discount_percent"] / 100), 2)
        discounted = round(due_now - max_discount_amount, 2)
        if discounted >= floor:
            offers.append(
                {
                    "type": "discount_settlement",
                    "amount": discounted,
                    "max_discount_percent": policy["max_discount_percent"],
                }
            )

    return {
        "total_outstanding": remaining,
        "due_now": due_now,
        "minimum_acceptable_today": floor,
        "cycle_days": cycle_days,
        "payments_to_clear": t["cycles_to_clear"],
        "offers": offers,
        "below_floor": below_floor,
        "exceeds_balance": exceeds_balance,
        "instruction": (
            f"They offered less than the minimum of {floor:g} for this cycle. Do not accept it, "
            "do not counter, and do not keep negotiating - say you can't agree to that on this "
            "call and escalate with mark_needs_review."
            if below_floor
            else (
                f"They have not named an amount yet. Do NOT assume zero and do NOT escalate. Ask "
                f"them what they CAN pay today, then call this tool again with that figure. "
                f"Anything from {floor:g} up to {due_now:g} is acceptable."
                if not named_amount
                else (
                    f"They offered {borrower_can_pay_today:g}, more than the {remaining:g} they actually "
                    f"owe. Confirm {remaining:g} - the full remaining balance - and send the payment "
                    f"link for that amount, not the figure they said."
                    if exceeds_balance
                    else (
                        f"They can pay {capped_amount:g}, which is acceptable. Confirm it and "
                        f"send the payment link. Never accept less than {floor:g}."
                    )
                )
            )
        ),
    }


def apply_discount(remaining: float, requested_pct: float, policy: dict) -> float | None:
    """Returns the settled amount, or None if the request is negative, not a
    real number, or exceeds policy and must go to human review."""
    _require_policy_fields(policy, "max_discount_percent")
    # NaN fails every comparison, so a bare range check waves it through and
    # returns a NaN settlement. Both bounds have to be asserted positively.
    try:
        requested_pct = float(requested_pct)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(requested_pct):
        return None
    if not (0 <= requested_pct <= policy["max_discount_percent"]):
        return None
    return round(remaining * (1 - requested_pct / 100), 2)
