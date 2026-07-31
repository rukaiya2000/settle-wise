"""Vapi tool webhook - outbound calling path.

a1mobile's own API has no outbound-calling capability (confirmed: its MCP
catalog exposes only claim/point/SMS/verify tools, every guessed REST
endpoint 404s, and a raw SIP INVITE with the claimed credentials never
completes digest auth even though REGISTER succeeds). Outbound is instead
reachable by registering those same SIP credentials as a Vapi BYO SIP trunk
- Vapi handles the trunk registration and INVITE auth, then dials out
through it.

That means Vapi runs the voice loop (its own STT/LLM/TTS) rather than our
Pipecat pipeline, so the agent reaches our negotiation logic through this
webhook. It dispatches to the exact same TOOL_DEFS registry used by the
realtime pipeline and the text console, so all three paths share one
implementation in server/agent/tools.py.
"""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from loguru import logger

from .. import config
from ..agent import tools as agent_tools
from ..agent.tool_registry import TOOL_DEFS
from ..db import get_conn
from ..demo_clock import get_demo_now

router = APIRouter()

TOOLS_BY_NAME = {t["name"]: t for t in TOOL_DEFS}


@router.post("/api/debts/{debt_id}/call")
def call_borrower(debt_id: str):
    """Place a real outbound call to this borrower's phone (the dashboard's
    'Call borrower' button). Distinct from /run-agent, which runs the
    deterministic simulator and never dials out."""
    from ..vapi_setup import place_call

    if not (config.VAPI_PRIVATE_KEY and config.VAPI_PHONE_NUMBER_ID and config.VAPI_ASSISTANT_ID):
        raise HTTPException(503, "Vapi is not set up - run: python -m server.vapi_setup setup")

    debt = agent_tools.get_debt_profile(debt_id)
    if "error" in debt:
        raise HTTPException(404, "not found")
    if not debt.get("phone"):
        raise HTTPException(400, f"{debt['name']} has no phone number on file")

    try:
        call = place_call(debt["phone"], debt_id)
    except SystemExit as e:  # vapi_setup raises SystemExit on API errors
        raise HTTPException(502, f"Vapi call failed: {e}")

    logger.info(f"[outbound call] {debt['name']} {debt['phone']} -> vapi call {call.get('id')}")
    return {
        "debt_id": debt_id,
        "name": debt["name"],
        "to": debt["phone"],
        "call_id": call.get("id"),
        "status": call.get("status"),
    }


@router.post("/api/vapi/tools")
async def vapi_tool_webhook(body: dict):
    """Vapi posts both tool calls and assistant server messages here.

    Only tool-calls expect Vapi's special {"results": [...]} response. End of
    call reports are informational, so we acknowledge after persisting the
    transcript and any fallback workflow state the assistant did not write via
    tools during the call.
    """
    message = body.get("message", {})
    message_type = message.get("type")
    if message_type == "end-of-call-report":
        return _handle_end_of_call_report(message)
    if message_type != "tool-calls":
        logger.info(f"[vapi event] {message_type}: call={_call_id(message)}")
        return {"received": True, "type": message_type}

    tool_calls = message.get("toolCallList", [])

    # Some tools take no debt_id (get_policy), which would orphan them from
    # the borrower's timeline. Vapi sends tool calls in batches, so borrow the
    # debt_id from a sibling call in the same batch.
    batch_debt_id = None
    for c in tool_calls:
        raw = (c.get("function") or {}).get("arguments", c.get("arguments")) or {}
        parsed = json.loads(raw or "{}") if isinstance(raw, str) else raw
        if parsed.get("debt_id"):
            batch_debt_id = parsed["debt_id"]
            break

    results = []
    for call in tool_calls:
        call_id = call.get("id")
        # Vapi nests these under "function" ({"function": {"name", "arguments"}})
        # and sends arguments as a JSON *string*, not an object. The flat
        # top-level shape in their docs is a simplification - accept both.
        fn = call.get("function") or {}
        name = fn.get("name") or call.get("name")
        arguments = fn.get("arguments", call.get("arguments")) or {}
        if isinstance(arguments, str):
            arguments = json.loads(arguments or "{}")

        tool = TOOLS_BY_NAME.get(name)
        if tool is None:
            logger.warning(f"Vapi requested unknown tool: {name}")
            results.append({"toolCallId": call_id, "result": {"error": f"unknown tool {name}"}})
            continue

        try:
            result = tool["fn"](**arguments)
        except Exception as e:
            logger.exception(f"Vapi tool {name} failed")
            result = {"error": f"{type(e).__name__}: {e}"}

        logger.info(f"[vapi tool] {name}({arguments}) -> {result}")
        _record_action(name, arguments, result, debt_id=arguments.get("debt_id") or batch_debt_id)
        results.append({"toolCallId": call_id, "result": result})

    return {"results": results}


def _record_action(tool: str, arguments: dict, result, source: str = "voice", debt_id: str | None = None):
    """Persist the tool call so the dashboard can replay exactly what the
    agent did. Never let bookkeeping break a live call."""
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO agent_actions (id, debt_id, tool, arguments, result, source, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f"act_{uuid.uuid4().hex[:8]}",
                    debt_id or arguments.get("debt_id"),
                    tool,
                    json.dumps(arguments, default=str),
                    json.dumps(result, default=str)[:2000],
                    source,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
    except Exception:
        logger.exception("failed to record agent action")


@router.post("/api/vapi/events")
async def vapi_event_webhook(body: dict):
    """Vapi server events. end-of-call-report carries the final transcript and
    summary; persist it even if the agent did not call our state-changing tools
    before the call ended."""
    message = body.get("message", {})
    if message.get("type") == "end-of-call-report":
        return _handle_end_of_call_report(message)
    logger.info(f"[vapi event] {message.get('type')}: call={_call_id(message)}")
    return {"ok": True}


def _handle_end_of_call_report(message: dict) -> dict:
    debt_id = _debt_id(message)
    if not debt_id:
        logger.warning(f"[vapi end-of-call] could not identify debt_id for call={_call_id(message)}")
        return {"received": True, "stored": False, "reason": "missing debt_id"}

    debt = agent_tools.get_debt_profile(debt_id)
    if "error" in debt:
        logger.warning(f"[vapi end-of-call] unknown debt_id={debt_id} call={_call_id(message)}")
        return {"received": True, "stored": False, "reason": "unknown debt_id"}

    transcript = _transcript(message)
    summary = _summary(message)
    outcome = _outcome(message, transcript, summary)
    call_id = _upsert_call_report(message, debt_id, outcome, summary, transcript)
    memory_written = _write_fallback_memory(debt_id, transcript, summary)
    next_action = _ensure_next_action(debt_id, outcome, summary)

    logger.info(
        f"[vapi end-of-call] debt={debt_id} call={_call_id(message)} "
        f"stored_call={call_id} outcome={outcome} transcript_len={len(transcript)}"
    )
    return {
        "received": True,
        "stored": True,
        "debt_id": debt_id,
        "call_id": call_id,
        "outcome": outcome,
        "memory_written": memory_written,
        "next_action": next_action,
    }


def _call_id(message: dict) -> str | None:
    call = message.get("call") or {}
    return call.get("id")


def _debt_id(message: dict) -> str | None:
    for candidate in _find_values(message, "debt_id"):
        if isinstance(candidate, str) and candidate.startswith("debt_"):
            return candidate

    customer = (message.get("call") or {}).get("customer") or {}
    phone = customer.get("number")
    if phone:
        normalized = _digits(phone)
        with get_conn() as conn:
            rows = conn.execute("SELECT id, phone FROM debts").fetchall()
        for row in rows:
            if _digits(row["phone"]) == normalized:
                return row["id"]
    return None


def _find_values(value, key: str):
    if isinstance(value, dict):
        for k, v in value.items():
            if k == key:
                yield v
            yield from _find_values(v, key)
    elif isinstance(value, list):
        for item in value:
            yield from _find_values(item, key)


def _digits(value: str) -> str:
    return re.sub(r"\D+", "", value or "")


def _transcript(message: dict) -> str:
    artifact = message.get("artifact") or {}
    transcript = artifact.get("transcript") or message.get("transcript") or ""
    if transcript:
        return transcript

    messages = artifact.get("messages") or message.get("messages") or []
    lines = []
    for item in messages:
        role = item.get("role") or item.get("type") or "speaker"
        text = item.get("message") or item.get("text") or item.get("content") or ""
        if isinstance(text, list):
            text = " ".join(str(part.get("text", part)) for part in text)
        if text:
            lines.append(f"{role}: {text}")
    return "\n".join(lines)


def _summary(message: dict) -> str:
    analysis = message.get("analysis") or {}
    structured = analysis.get("structuredData") or {}
    summary = (
        message.get("summary")
        or analysis.get("summary")
        or structured.get("summary")
        or message.get("endedReason")
        or "Vapi call ended."
    )
    return str(summary)


def _outcome(message: dict, transcript: str, summary: str) -> str:
    text = f"{message.get('endedReason', '')} {summary}".lower()
    if any(term in text for term in ["dispute", "wrong person", "fraud", "identity theft"]):
        return "needs_review"
    if any(term in text for term in ["paid", "payment completed"]):
        return "paid"
    if any(term in text for term in ["promise", "promised", "agreed to pay", "payment link"]):
        return "promised"
    if any(term in text for term in ["callback", "call back", "later"]):
        return "callback_requested"
    if not transcript.strip() or any(term in text for term in ["no-answer", "busy", "voicemail", "silence-timed-out"]):
        return "no_answer"
    return "answered"


def _upsert_call_report(message: dict, debt_id: str, outcome: str, summary: str, transcript: str) -> str:
    now = get_demo_now().isoformat()
    vapi_call_id = _stored_call_id(message)
    with get_conn() as conn:
        if vapi_call_id:
            row = conn.execute("SELECT id FROM calls WHERE id = ?", (vapi_call_id,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE calls SET outcome = ?, transcript = ?, summary = ? WHERE id = ?",
                    (outcome, transcript, summary, vapi_call_id),
                )
                conn.execute("UPDATE debts SET last_call_summary = ? WHERE id = ?", (summary, debt_id))
                return vapi_call_id

        if transcript:
            row = conn.execute(
                """SELECT id FROM calls
                   WHERE debt_id = ? AND transcript = ?
                   ORDER BY started_at DESC
                   LIMIT 1""",
                (debt_id, transcript),
            ).fetchone()
            if row:
                conn.execute("UPDATE debts SET last_call_summary = ? WHERE id = ?", (summary, debt_id))
                return row["id"]

        row = conn.execute(
            """SELECT id, transcript, summary FROM calls
               WHERE debt_id = ?
               ORDER BY started_at DESC
               LIMIT 1""",
            (debt_id,),
        ).fetchone()
        if row and not row["transcript"]:
            conn.execute(
                """UPDATE calls
                   SET outcome = COALESCE(outcome, ?),
                       transcript = ?,
                       summary = CASE WHEN summary = '' THEN ? ELSE summary END
                   WHERE id = ?""",
                (outcome, transcript, summary, row["id"]),
            )
            call_id = row["id"]
        else:
            call_id = vapi_call_id or f"call_{_digits(_call_id(message) or '')[:8]}"
            if call_id == "call_":
                call = agent_tools.record_call_event(
                    debt_id=debt_id,
                    outcome=outcome,
                    summary=summary,
                    transcript=transcript,
                )
                call_id = call["call_id"]
            else:
                conn.execute(
                    """INSERT INTO calls (id, debt_id, started_at, outcome, transcript, summary)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (call_id, debt_id, now, outcome, transcript, summary),
                )

        conn.execute("UPDATE debts SET last_call_summary = ? WHERE id = ?", (summary, debt_id))
    return call_id


def _stored_call_id(message: dict) -> str | None:
    call_id = _call_id(message)
    if not call_id:
        return None
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", call_id).strip("_")
    return f"vapi_{normalized[:48]}" if normalized else None


def _write_fallback_memory(debt_id: str, transcript: str, summary: str) -> list[dict]:
    text = f"{transcript}\n{summary}"
    written = []

    salary_match = re.search(
        r"\b(?:salary|payday|paid)\s+(?:is\s+)?(?:on\s+)?([A-Za-z]+day|[A-Za-z]{3,9}\s+\d{1,2}|\d{1,2}/\d{1,2}|\d{4}-\d{2}-\d{2})",
        text,
        re.IGNORECASE,
    )
    if salary_match:
        written.append(agent_tools.write_memory(debt_id, "salary_date", salary_match.group(1)))

    if re.search(r"\b(?:do not call|stop calling|no more calls|don't call)\b", text, re.IGNORECASE):
        written.append(agent_tools.write_memory(debt_id, "no_contact", "Borrower asked not to be called again."))

    callback_match = re.search(
        r"\b(?:call me back|callback|call back)\s+(?:on\s+|at\s+|after\s+)?([A-Za-z]+day|tomorrow|[A-Za-z]{3,9}\s+\d{1,2}|\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        text,
        re.IGNORECASE,
    )
    if callback_match:
        written.append(agent_tools.write_memory(debt_id, "callback_preference", callback_match.group(1)))

    return written


def _ensure_next_action(debt_id: str, outcome: str, summary: str) -> dict | None:
    debt = agent_tools.get_debt_profile(debt_id)
    if "error" in debt or debt["status"] not in {"new", "no_answer"}:
        return None

    if outcome in {"paid", "needs_review", "promised"}:
        return None

    next_time = _next_action_at(summary)
    return agent_tools.schedule_next_action(
        debt_id,
        next_action="call_borrower",
        next_action_at=next_time,
        reason=summary,
    )


def _next_action_at(summary: str) -> str:
    now = get_demo_now()
    if re.search(r"\btomorrow\b", summary, re.IGNORECASE):
        return (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0).isoformat()
    return (now + timedelta(days=1)).isoformat()
