"""Compose a pre-call recommendation from what R already computed.

This is deliberately a rule table, not a model and not an LLM. Every field
in the recommendation is a lookup into a stored analysis output (the
prediction, the segment profile, the neighbour cohort, a finding) plus a
handful of explicit rules written out below. That keeps the
recommendation auditable - each line of "why" cites an evidence id that
resolves to a row R wrote - and it keeps the boundary the whole project is
built on: nothing here can change a payment amount, lower a floor, or
skip a human review. It suggests who to call, when, and how.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime

from ..db import get_conn, row_to_dict, rows_to_dicts

BUCKET_WINDOWS = {"morning": "09:00-12:00", "afternoon": "12:00-17:00", "evening": "17:00-20:00"}

# Conversation style by segment. Copy the voice agent can be primed with;
# it never changes what the agent is allowed to offer.
STYLE_BY_LABEL = {
    "Prompt payers": ("direct", "State the amount and send the link; little negotiation needed."),
    "Delayed but responsive": ("direct_and_flexible", "Ask for a specific date, then a reminder the day before."),
    "Hardship": ("empathetic_options", "Lead with the approved options and the floor; expect objections."),
    "Hard to reach": ("brief_link_first", "Keep it short and text the link; escalate after repeated no-answers."),
}
DEFAULT_STYLE = ("direct_and_flexible", "Standard approach; not enough history to specialise.")


def _one(conn, sql, *args):
    return row_to_dict(conn.execute(sql, args).fetchone())


def intelligence_available(conn) -> bool:
    return conn.execute("SELECT COUNT(*) FROM borrower_features").fetchone()[0] > 0


def borrower_intelligence(debt_id: str) -> dict:
    """Everything the borrower page shows, in one call. Degrades to
    available=False when R has not run yet, so the page still renders.

    Schema creation happens once at app startup (server/main.py), not here -
    this is called on every borrower-page load and tab focus."""
    with get_conn() as conn:
        debt = _one(conn, "SELECT * FROM debts WHERE id = ?", debt_id)
        if debt is None:
            return {"available": False, "reason": "unknown debt"}
        if not intelligence_available(conn):
            return {"available": False, "reason": "intelligence layer has not been built yet - run `make intelligence`"}

        features = _one(conn, "SELECT * FROM borrower_features WHERE debt_id = ?", debt_id)
        segment = _one(conn, "SELECT * FROM borrower_segments WHERE debt_id = ?", debt_id)
        profile = _one(conn, "SELECT * FROM segment_profiles WHERE community = ?", segment["community"]) if segment else None
        prediction = _one(
            conn,
            "SELECT * FROM predictions WHERE debt_id = ? AND prediction_type = 'payment_after_next_contact' ORDER BY generated_at DESC LIMIT 1",
            debt_id,
        )
        neighbors = rows_to_dicts(conn, "SELECT * FROM borrower_neighbors WHERE debt_id = ? ORDER BY rank LIMIT 10", debt_id)
        findings = rows_to_dicts(
            conn,
            "SELECT * FROM statistical_findings WHERE segment_label IS NULL OR segment_label = ? ORDER BY analysis_name",
            (segment or {}).get("segment_label"),
        )
        if features is None:
            return {"available": False, "reason": "no features for this borrower yet - run `make intelligence` after the latest call"}

        rec = compose(debt, features, segment, profile, prediction, neighbors, findings)
        rec_id = _store(conn, debt_id, rec)
        rec["recommendation_id"] = rec_id

    if prediction and prediction.get("explanation_json"):
        prediction["explanation"] = json.loads(prediction.pop("explanation_json"))
    return {
        "available": True,
        "debt_id": debt_id,
        "features": features,
        "segment": segment,
        "segment_profile": profile,
        "prediction": prediction,
        "neighbors": neighbors,
        "recommendation": rec,
    }


def _base_archetype(label: str | None) -> str | None:
    """The R side appends " (2)", " (3)", ... to segment_label when two
    communities land on the same archetype (intelligence/R/02_network.R
    label_communities), so anything matching on the label verbatim - a style
    lookup, the hardship-escalation rule below - would silently miss any but
    the first such community. Strip the numbering suffix before matching."""
    return re.sub(r" \(\d+\)$", "", label) if label else label


def compose(debt: dict, features: dict, segment: dict | None, profile: dict | None, prediction: dict | None, neighbors: list[dict], findings: list[dict]) -> dict:
    label = (segment or {}).get("segment_label")
    style, style_note = STYLE_BY_LABEL.get(_base_archetype(label), DEFAULT_STYLE)
    low_history = bool(features.get("low_history"))
    prob = prediction["prediction_value"] if prediction else None
    evidence: list[dict] = []
    why: list[str] = []

    # -- Contact window: the segment's best hour bucket, falling back to
    # the borrower's own preferred bucket, falling back to policy hours.
    bucket = (profile or {}).get("best_bucket") or features.get("preferred_bucket") or "afternoon"
    window = BUCKET_WINDOWS.get(bucket, "09:00-20:00")
    if profile and profile.get("best_bucket"):
        why.append(
            f"Borrowers in the \"{profile['segment_label']}\" segment answered most often in the {profile['best_bucket']} "
            f"({round(100 * (profile.get('best_bucket_rate') or 0))}% contact rate)."
        )
        evidence.append({"type": "segment_profile", "id": f"segment_{profile['community']}"})

    # -- Payment probability, with the model's own explanation.
    if prediction:
        pct = round(100 * prob)
        why.append(f"The model puts payment after the next contact at {pct}% (model {prediction.get('model_version')}).")
        evidence.append({"type": "prediction", "id": prediction["prediction_id"]})
        expl = json.loads(prediction.get("explanation_json") or "[]")
        for item in expl[:3]:
            sign = "+" if item.get("direction") == "up" else "-"
            why.append(f"{sign} {item.get('label')}")

    # -- Similar borrowers: what happened to the nearest historical cohort.
    if neighbors:
        paid = [n for n in neighbors if n.get("neighbor_paid")]
        rate = round(100 * len(paid) / len(neighbors))
        why.append(f"Of the {len(neighbors)} most similar historical borrowers, {rate}% went on to pay.")
        evidence.append({"type": "neighbors", "id": f"neighbors_{debt['id']}"})

    # -- Statistical findings that apply to this segment (or globally).
    for f in findings:
        if f.get("significant"):
            evidence.append({"type": "finding", "id": f["finding_id"]})

    # -- Action. Rules, in order; the first that matches wins.
    if debt["status"] == "needs_review":
        action, human = "human_review", True
        why.insert(0, "This account is already in human review; no automated contact until a person has looked at it.")
    elif debt["status"] == "paid":
        action, human = "none", False
        why.insert(0, "Balance is cleared - nothing to do.")
    elif (features.get("n_calls") or 0) >= 5 and (features.get("contact_success_rate") or 0) < 0.15:
        action, human = "sms", False
        why.insert(0, "Five or more calls with almost no pick-ups - text the link rather than dial again.")
    elif _base_archetype(label) == "Hardship" and (features.get("objection_rate") or 0) >= 0.5:
        action, human = "call", True
        why.insert(0, "Repeated affordability objections - call with the approved options, and have a person ready to review.")
    else:
        action, human = "call", False

    if low_history:
        why.append("Little history on this account yet, so the segment and probability lean on the portfolio prior.")

    return {
        "debt_id": debt["id"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "recommended_next_action": action,
        "recommended_contact_window": window,
        "recommended_contact_bucket": bucket,
        "recommended_style": style,
        "style_note": style_note,
        "predicted_payment_probability": prob,
        "behavior_segment": label,
        "human_review_recommended": human,
        "low_history": low_history,
        "why": why,
        "evidence": evidence,
        "note": "Recommendation only. Any amount, discount, or floor still goes through the offer engine; this cannot change them.",
    }


def _store(conn, debt_id: str, rec: dict) -> str:
    # The borrower page recomputes this on every route() (including just
    # tab-focus), so without a dedupe check, alt-tabbing back to an open
    # page would mint an identical row every time. Reuse the latest row
    # if nothing but the timestamp changed.
    latest = _one(
        conn, "SELECT recommendation_id, recommendation_json FROM recommendations WHERE debt_id = ? ORDER BY generated_at DESC LIMIT 1", debt_id
    )
    if latest is not None:
        prior = json.loads(latest["recommendation_json"])
        prior.pop("generated_at", None)
        current = {k: v for k, v in rec.items() if k != "generated_at"}
        if prior == current:
            return latest["recommendation_id"]

    rec_id = f"rec_{uuid.uuid4().hex[:8]}"
    conn.execute(
        "INSERT INTO recommendations (recommendation_id, debt_id, generated_at, recommendation_json, evidence_ids) VALUES (?, ?, ?, ?, ?)",
        (rec_id, debt_id, rec["generated_at"], json.dumps(rec), json.dumps([e["id"] for e in rec["evidence"]])),
    )
    return rec_id


def record_outcome(debt_id: str, executed_action: str | None, observed_outcome: str | None) -> dict | None:
    """Close the loop on the latest recommendation for a debt. Called after
    a call is recorded so recommendation -> action -> outcome is one row."""
    with get_conn() as conn:
        latest = _one(conn, "SELECT recommendation_id FROM recommendations WHERE debt_id = ? ORDER BY generated_at DESC LIMIT 1", debt_id)
        if latest is None:
            return None
        conn.execute(
            "UPDATE recommendations SET executed_action = COALESCE(?, executed_action), observed_outcome = COALESCE(?, observed_outcome) WHERE recommendation_id = ?",
            (executed_action, observed_outcome, latest["recommendation_id"]),
        )
        return latest
