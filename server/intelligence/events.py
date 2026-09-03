"""Shared vocabulary for interaction_events.

The synthetic generator and the live extractor both produce rows for the
same table, so the words they use for an outcome have to agree or the
analysis silently splits one behaviour into two. Everything that decides
what an event is called goes through here.
"""

import json
from datetime import datetime

# Call attempt outcomes. The first six mirror the operational vocabulary in
# server/agent/post_call_analysis.py:OUTCOMES; the rest only exist in the
# richer synthetic history (a live call records "answered" plus a summary).
NO_ANSWER = "no_answer"
ANSWERED_OTHER = "answered_other"
CALLBACK_REQUESTED = "callback_requested"
ANSWERED_PROMISED = "answered_promised"
ANSWERED_PAID = "answered_paid"
ANSWERED_OBJECTION = "answered_objection"
ANSWERED_REFUSED = "answered_refused"
REQUESTED_HUMAN = "requested_human"
DISPUTE = "dispute"

ANSWERED_OUTCOMES = {
    ANSWERED_OTHER,
    CALLBACK_REQUESTED,
    ANSWERED_PROMISED,
    ANSWERED_PAID,
    ANSWERED_OBJECTION,
    ANSWERED_REFUSED,
    REQUESTED_HUMAN,
    DISPUTE,
}
ESCALATION_OUTCOMES = {REQUESTED_HUMAN, DISPUTE}

# SMS / payment / escalation outcomes.
REMINDER_SENT = "reminder_sent"
LINK_SENT = "link_sent"
PAID_FULL = "paid_full"
PAID_PARTIAL = "paid_partial"
NEEDS_REVIEW = "needs_review"

# Hour buckets. Evening is deliberately narrow (17-20) so it lines up with
# the policy's allowed_call_hours_end of 20:00.
BUCKETS = {"morning": (9, 12), "afternoon": (12, 17), "evening": (17, 20)}


def bucket_for_hour(hour: int) -> str:
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts[:19])


def build_event_fields(
    debt_id: str, event_id: str, when: datetime, event_type: str, channel: str, outcome: str,
    strategy: str | None, outstanding: float, **extra,
) -> dict:
    """The interaction_events row shape, shared by the synthetic generator
    and the live extractor - only the event_id format and cohort differ
    between the two, so this is everything else."""
    return {
        "event_id": event_id,
        "debt_id": debt_id,
        "event_time": when.isoformat(timespec="seconds"),
        "event_type": event_type,
        "channel": channel,
        "hour": when.hour,
        "time_bucket": bucket_for_hour(when.hour),
        "weekday": when.weekday(),
        "outcome": outcome,
        "strategy": strategy,
        "amount_due_at_event": round(outstanding, 2),
        "amount_offered": extra.get("amount_offered"),
        "amount_paid": extra.get("amount_paid"),
        "response_time_seconds": extra.get("response_time_seconds"),
        "metadata_json": json.dumps(extra.get("meta", {})),
    }


def operational_call_outcome_to_event(outcome: str | None, summary: str = "") -> str:
    """Map a live call's outcome + summary to the event vocabulary.

    A live call only stores one of six coarse outcomes. The summary text is
    the only place an objection or a "put me through to a person" survives,
    so a few keyword rules recover it. They are deliberately simple and
    listed here in one place; they are not an NLP model.
    """
    s = (summary or "").lower()
    if outcome == "no_answer":
        return NO_ANSWER
    if outcome == "promised":
        return ANSWERED_PROMISED
    if outcome == "paid":
        return ANSWERED_PAID
    if outcome == "callback_requested":
        return CALLBACK_REQUESTED
    if outcome == "needs_review":
        if "disput" in s or "wrong person" in s or "fraud" in s:
            return DISPUTE
        return REQUESTED_HUMAN
    # "answered" and anything unknown: something was said but nothing agreed.
    if "refus" in s or "won't pay" in s or "will not pay" in s:
        return ANSWERED_REFUSED
    if any(w in s for w in ("afford", "hardship", "can't pay", "cannot pay", "too much", "objection", "lost my job")):
        return ANSWERED_OBJECTION
    return ANSWERED_OTHER
