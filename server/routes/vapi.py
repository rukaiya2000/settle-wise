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

from fastapi import APIRouter, HTTPException
from loguru import logger

from .. import config
from ..agent import tools as agent_tools
from ..agent.tool_registry import TOOL_DEFS

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
        results.append({"toolCallId": call_id, "result": result})

    return {"results": results}
