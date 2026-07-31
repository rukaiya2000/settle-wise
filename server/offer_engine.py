"""Deterministic offer generation per md/technical-spec.md "Agent Tool Surface".

Policy-driven: max discount, min payment-today percent, and installment cap
come from the synthetic policy (server/policy.py) rather than being
hardcoded, so tuning the demo happens in one place. The agent must not
invent an offer outside what this returns (md/agent-behavior.md negotiation
rules).
"""


def generate_offer_options(
    amount_due: float,
    amount_collected: float,
    policy: dict,
    borrower_can_pay_today: float | None = None,
    has_future_income_date: bool = False,
) -> list[dict]:
    remaining = round(amount_due - amount_collected, 2)
    offers = [{"type": "pay_today", "amount": remaining}]

    if borrower_can_pay_today is not None and borrower_can_pay_today < remaining:
        min_today = round(remaining * (policy["min_payment_today_percent"] / 100), 2)
        amount_today = max(borrower_can_pay_today, 0)
        amount_today = max(amount_today, min_today) if amount_today > 0 else min_today
        amount_today = min(amount_today, remaining)
        offers.append(
            {
                "type": "partial",
                "amount_today": amount_today,
                "remaining": round(remaining - amount_today, 2),
            }
        )

    if has_future_income_date and policy["max_installments"] > 1:
        n = int(policy["max_installments"])
        base = round(remaining / n, 2)
        installments = [base] * (n - 1)
        installments.append(round(remaining - base * (n - 1), 2))
        offers.append({"type": "installment", "installments": installments})

    max_discount_amount = round(remaining * (policy["max_discount_percent"] / 100), 2)
    offers.append(
        {
            "type": "discount_settlement",
            "amount": round(remaining - max_discount_amount, 2),
            "max_discount_percent": policy["max_discount_percent"],
        }
    )

    return offers


def apply_discount(remaining: float, requested_pct: float, policy: dict) -> float | None:
    """Returns the settled amount, or None if the request exceeds policy
    and must go to human review."""
    if requested_pct > policy["max_discount_percent"]:
        return None
    return round(remaining * (1 - requested_pct / 100), 2)
