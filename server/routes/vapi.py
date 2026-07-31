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
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from loguru import logger

from .. import config
from ..agent import tools as agent_tools
from ..agent.tool_registry import TOOL_DEFS
from ..db import get_conn

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
    """Vapi posts {"message": {"type": "tool-calls", "toolCallList": [...]}}
    and expects {"results": [{"toolCallId": ..., "result": ...}]}."""
    message = body.get("message", {})
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
    """Vapi server events. We only care about end-of-call-report, which
    carries the transcript and summary - without this a real call leaves no
    readable record on the borrower's page, since the tool trace alone
    doesn't show what was actually said."""
    message = body.get("message", {})
    if message.get("type") != "end-of-call-report":
        return {"ok": True}

    call = message.get("call") or {}
    debt_id = ((call.get("assistantOverrides") or {}).get("variableValues") or {}).get("debt_id")
    transcript = message.get("transcript") or ""
    summary = message.get("summary") or ""
    ended_reason = message.get("endedReason") or ""

    if not debt_id:
        logger.warning("end-of-call-report with no debt_id, skipping")
        return {"ok": True}

    with get_conn() as conn:
        # The agent usually logs its own outcome via record_call_event during
        # the call. Attach the transcript to that row rather than inserting a
        # second one, so one phone call is one row in the history.
        existing = conn.execute(
            "SELECT id FROM calls WHERE debt_id = ? AND (transcript IS NULL OR transcript = '') "
            "ORDER BY started_at DESC LIMIT 1",
            (debt_id,),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE calls SET transcript = ?, summary = COALESCE(NULLIF(summary, ''), ?) WHERE id = ?",
                (transcript, summary or f"Call ended: {ended_reason}", existing["id"]),
            )
            call_id = existing["id"]
        else:
            call_id = f"call_{uuid.uuid4().hex[:8]}"
            conn.execute(
                """INSERT INTO calls (id, debt_id, started_at, outcome, transcript, summary)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    call_id,
                    debt_id,
                    agent_tools._now_iso(),
                    "answered" if transcript else ended_reason,
                    transcript,
                    summary or f"Call ended: {ended_reason}",
                ),
            )

    logger.info(f"[vapi call ended] {debt_id} {ended_reason} -> {call_id}, transcript {len(transcript)} chars")
    return {"ok": True}
