"""LLM post-call analysis for Vapi transcripts.

The live agent should update state with tools during the call, but calls can
end before those tools run. This module turns the final transcript into one
structured workflow decision so persistence is model-driven rather than a set
of route-level keyword extractors.
"""

import json

from .. import config
from ..demo_clock import get_demo_now

OUTCOMES = {"answered", "no_answer", "callback_requested", "promised", "paid", "needs_review"}
NEXT_ACTIONS = {"none", "call_borrower", "send_sms_reminder", "human_review"}


def analyze_post_call(debt: dict, transcript: str, ended_reason: str = "") -> dict:
    from .. import llm  # lazy: openai is ~half the import cost of a cold start, and only this path needs it

    client = llm.chat_client(timeout=30)
    response = client.chat.completions.create(
        model=config.OPENAI_POST_CALL_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You analyze completed debt-collection phone call transcripts. "
                    "Return only valid JSON. Do not include markdown."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "Summarize the call, extract durable memory facts, and decide the next workflow action.",
                        "schema": {
                            "summary": "short human-readable summary",
                            "outcome": sorted(OUTCOMES),
                            "memory_facts": [
                                {
                                    "key": "short_snake_case_key",
                                    "value": "durable fact learned from the transcript",
                                }
                            ],
                            "next_action": {
                                "type": sorted(NEXT_ACTIONS),
                                "at": "ISO-8601 datetime or null",
                                "reason": "why this action should happen",
                            },
                        },
                        "borrower": {
                            "debt_id": debt["id"],
                            "name": debt["name"],
                            "phone": debt["phone"],
                            "status_before_analysis": debt["status"],
                            "amount_due": debt["amount_due"],
                            "amount_collected": debt["amount_collected"],
                            "amount_promised": debt["amount_promised"],
                            "due_date": debt["due_date"],
                            "next_action_before_analysis": debt["next_action"],
                            "next_action_at_before_analysis": debt["next_action_at"],
                        },
                        "demo_now": get_demo_now().isoformat(),
                        "ended_reason": ended_reason,
                        "transcript": transcript,
                    },
                    default=str,
                ),
            },
        ],
    )
    return _validate_analysis(_response_text(response))


def _response_text(response) -> str:
    text = response.choices[0].message.content if response.choices else None
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("post-call analysis response had no text")
    return text


def _validate_analysis(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json").strip()

    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("post-call analysis must be a JSON object")

    summary = str(data.get("summary") or "Call analyzed.").strip()
    outcome = data.get("outcome")
    if outcome not in OUTCOMES:
        outcome = "answered"

    facts = data.get("memory_facts") or data.get("facts") or []
    if not isinstance(facts, list):
        facts = []
    memory_facts = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        key = str(fact.get("key") or "").strip()
        value = str(fact.get("value") or "").strip()
        if key and value:
            memory_facts.append({"key": key[:80], "value": value[:500]})

    next_action = data.get("next_action") or {}
    if not isinstance(next_action, dict):
        next_action = {}
    action_type = next_action.get("type")
    if action_type not in NEXT_ACTIONS:
        action_type = "none"

    return {
        "summary": summary[:1000],
        "outcome": outcome,
        "memory_facts": memory_facts,
        "next_action": {
            "type": action_type,
            "at": next_action.get("at"),
            "reason": str(next_action.get("reason") or summary).strip()[:1000],
        },
    }
