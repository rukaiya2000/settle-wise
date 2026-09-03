"""Turn live operational rows into interaction_events.

    python -m server.intelligence.extract

Every borrower on the dashboard gets the same flat event log the historical
cohort has, built from calls, sms_messages and the debt row itself. It is
rebuilt from scratch on every run (cohort = 'live' rows only), so it is
always a pure function of the operational tables and never drifts from
them. Anything R computes for a live borrower is therefore explainable
back to a call or a text on their page.
"""

from __future__ import annotations

import json
from datetime import datetime

from .. import config
from ..db import get_conn
from ..demo_clock import get_demo_now
from . import events as ev
from .schema import init_intel_db, insert_intel_rows


def _event(debt_id: str, seq: int, when: datetime, event_type: str, channel: str, outcome: str, strategy: str | None, outstanding: float, **extra) -> dict:
    fields = ev.build_event_fields(debt_id, f"evt_{debt_id}_live_{seq:03d}", when, event_type, channel, outcome, strategy, outstanding, **extra)
    fields["cohort"] = "live"
    return fields


def extract_debt(conn, debt: dict, strategy_lookup: dict[str, str], now: datetime) -> tuple[dict, list[dict]]:
    debt_id = debt["id"]
    strategy = strategy_lookup.get(debt_id, "standard")
    calls = [dict(r) for r in conn.execute("SELECT * FROM calls WHERE debt_id = ? ORDER BY started_at", (debt_id,))]
    sms = [dict(r) for r in conn.execute("SELECT * FROM sms_messages WHERE debt_id = ? ORDER BY sent_at", (debt_id,))]

    rows: list[dict] = []
    paid_so_far = 0.0
    first_payment: datetime | None = None
    last_link_at: datetime | None = None
    seq = 0

    timeline: list[tuple[datetime, str, dict]] = []
    for c in calls:
        timeline.append((ev.parse_iso(c["started_at"]), "call", c))
    for s in sms:
        timeline.append((ev.parse_iso(s["sent_at"]), "sms", s))
    timeline.sort(key=lambda t: t[0])

    for when, kind, row in timeline:
        outstanding = debt["amount_due"] - paid_so_far
        seq += 1
        if kind == "call":
            outcome = ev.operational_call_outcome_to_event(row.get("outcome"), row.get("summary", ""))
            rows.append(_event(debt_id, seq, when, "call_attempt", "voice", outcome, strategy, outstanding,
                               amount_offered=row.get("amount_promised"), meta={"call_id": row["id"]}))
            if outcome in ev.ESCALATION_OUTCOMES:
                seq += 1
                rows.append(_event(debt_id, seq, when, "escalation", "system", ev.NEEDS_REVIEW, strategy, outstanding,
                                   meta={"reason": row.get("summary", "")}))
            continue

        stype = row.get("type")
        if stype == "reminder":
            rows.append(_event(debt_id, seq, when, "sms", "sms", ev.REMINDER_SENT, strategy, outstanding, amount_offered=row.get("amount")))
        elif stype == "payment_link":
            last_link_at = when
            rows.append(_event(debt_id, seq, when, "sms", "sms", ev.LINK_SENT, strategy, outstanding, amount_offered=row.get("amount")))
        elif stype == "confirmation":
            amount = float(row.get("amount") or 0)
            paid_so_far += amount
            response = (when - last_link_at).total_seconds() if last_link_at else None
            outcome = ev.PAID_FULL if paid_so_far >= debt["amount_due"] - 0.01 else ev.PAID_PARTIAL
            rows.append(_event(debt_id, seq, when, "payment", "link", outcome, strategy, outstanding,
                               amount_paid=amount, response_time_seconds=response))
            if first_payment is None:
                first_payment = when
        else:
            rows.append(_event(debt_id, seq, when, "sms", "sms", "custom_sent", strategy, outstanding))

    # Escalation recorded on the debt but never on a call (e.g. the
    # scheduler or a dashboard action flagged it).
    if debt["status"] == "needs_review" and not any(r["event_type"] == "escalation" for r in rows):
        seq += 1
        when = timeline[-1][0] if timeline else ev.parse_iso(debt.get("due_date", config.DEMO_CLOCK_START[:10]) + "T09:00:00")
        rows.append(_event(debt_id, seq, when, "escalation", "system", ev.NEEDS_REVIEW, strategy, debt["amount_due"] - paid_so_far,
                           meta={"reason": debt.get("last_call_summary", "")}))

    opened = ev.parse_iso((debt.get("due_date") or config.DEMO_CLOCK_START[:10]) + "T09:00:00")
    if timeline:
        opened = min(opened, timeline[0][0])
    if first_payment is not None:
        days, observed = (first_payment - opened).total_seconds() / 86400, 1
    else:
        days, observed = max(0.0, (now - opened).total_seconds() / 86400), 0

    final = "paid" if debt["status"] == "paid" else ("needs_review" if debt["status"] == "needs_review" else "open")
    intel = {
        "debt_id": debt_id,
        "cohort": "live",
        "amount_due": debt["amount_due"],
        "strategy": strategy,
        "opened_at": opened.isoformat(timespec="seconds"),
        "closed_at": None if final == "open" else now.isoformat(timespec="seconds"),
        "final_outcome": final,
        "paid": 1 if first_payment else 0,
        "days_to_payment": round(days, 2),
        "observed": observed,
    }
    return intel, rows


def _strategy_lookup() -> dict[str, str]:
    """Live borrowers from the synthetic book carry their randomised
    strategy in live_book.json; anyone else defaults to 'standard'."""
    path = config.BASE_DIR / "data" / "synthetic" / "live_book.json"
    if not path.exists():
        return {}
    book = json.loads(path.read_text())
    return {d["id"]: d.get("strategy", "standard") for d in book.get("debts", [])}


def extract_all() -> dict:
    init_intel_db()
    lookup = _strategy_lookup()
    now = get_demo_now()
    with get_conn() as conn:
        debts = [dict(r) for r in conn.execute("SELECT * FROM debts")]
        conn.execute("DELETE FROM interaction_events WHERE cohort = 'live'")
        conn.execute("DELETE FROM intel_borrowers WHERE cohort = 'live'")
        n_events = 0
        for debt in debts:
            intel, rows = extract_debt(conn, debt, lookup, now)
            insert_intel_rows(conn, intel, rows)
            n_events += len(rows)
    return {"debts": len(debts), "events": n_events}


if __name__ == "__main__":
    print(json.dumps(extract_all()))
