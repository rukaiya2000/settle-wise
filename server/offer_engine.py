"""Deterministic offer ladder per md/mvp-scope.md.

Priority order: full payment -> partial payment -> installment plan
(only if a future income date is known) -> discount/settlement (capped) ->
human review. The agent must not invent offers outside this ladder
(md/agent-behavior.md negotiation rules).
"""

from dataclasses import dataclass

from . import config


@dataclass
class Offer:
    kind: str
    label: str
    amount: float
    conditions: str


def build_offer_ladder(amount_due: float, has_future_income_date: bool) -> list[Offer]:
    ladder = [
        Offer("full_payment", "Full payment today", amount_due, "Default first ask"),
        Offer(
            "partial_payment",
            "Partial payment today plus remainder before breach",
            amount_due,
            "Borrower cannot pay full today",
        ),
    ]
    if has_future_income_date:
        ladder.append(
            Offer(
                "installment_plan",
                "Installment plan",
                amount_due,
                "Debt is eligible and borrower has a future income date",
            )
        )
    max_discount = round(amount_due * (config.MAX_DISCOUNT_PCT / 100), 2)
    ladder.append(
        Offer(
            "discount_settlement",
            f"Discount or settlement (max {config.MAX_DISCOUNT_PCT:.0f}%)",
            round(amount_due - max_discount, 2),
            f"Simple rule: max {config.MAX_DISCOUNT_PCT:.0f}% discount",
        )
    )
    return ladder


def apply_discount(amount_due: float, requested_pct: float) -> float | None:
    """Returns the settled amount, or None if the request exceeds policy
    and must go to human review (md/mvp-scope.md offer ladder, priority 5)."""
    if requested_pct > config.MAX_DISCOUNT_PCT:
        return None
    return round(amount_due * (1 - requested_pct / 100), 2)
