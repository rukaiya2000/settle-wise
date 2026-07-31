"""One-time Vapi setup for outbound calling, plus a dial command.

Registers the a1mobile SIP credentials as a Vapi BYO SIP trunk, creates the
tools/assistant that point back at our own webhook
(server/routes/vapi.py -> the shared TOOL_DEFS registry), and can then place
an outbound call.

    .venv/bin/python -m server.vapi_setup setup
    .venv/bin/python -m server.vapi_setup call +1YOURNUMBER debt_002

Needs in .env:
    VAPI_PRIVATE_KEY=...
    PUBLIC_BASE_URL=https://your-ngrok-host   (no trailing slash)
Written back to .env by `setup`:
    VAPI_CREDENTIAL_ID, VAPI_PHONE_NUMBER_ID, VAPI_ASSISTANT_ID
"""

import json
import sys

import requests

from . import config
from .agent import SYSTEM_PROMPT
from .agent.tool_registry import TOOL_DEFS

VAPI_API = "https://api.vapi.ai"


def _headers() -> dict:
    if not config.VAPI_PRIVATE_KEY:
        raise SystemExit("VAPI_PRIVATE_KEY is not set in .env")
    return {
        "Authorization": f"Bearer {config.VAPI_PRIVATE_KEY}",
        "Content-Type": "application/json",
    }


def _post(path: str, payload: dict) -> dict:
    r = requests.post(f"{VAPI_API}{path}", headers=_headers(), json=payload)
    if not r.ok:
        raise SystemExit(f"POST {path} failed: {r.status_code} {r.text}")
    return r.json()


def _patch(path: str, payload: dict) -> dict:
    r = requests.patch(f"{VAPI_API}{path}", headers=_headers(), json=payload)
    if not r.ok:
        raise SystemExit(f"PATCH {path} failed: {r.status_code} {r.text}")
    return r.json()


def create_sip_trunk() -> dict:
    """Register a1mobile's SIP credentials as a BYO SIP trunk. Vapi performs
    the trunk registration and INVITE digest auth against sip.telnyx.com that
    a raw SIP client could not complete on its own."""
    return _post(
        "/credential",
        {
            "provider": "byo-sip-trunk",
            "name": "a1mobile-telnyx",
            # inboundEnabled must be false to use a hostname here - Vapi only
            # accepts a numeric IPv4 for inbound gateways. We only dial out;
            # inbound still arrives via a1mobile's webhook (server/routes/voice.py).
            "gateways": [{"ip": "sip.telnyx.com", "inboundEnabled": False}],
            "outboundLeadingPlusEnabled": True,
            "outboundAuthenticationPlan": {
                "authUsername": config.A1MOBILE_SIP_USERNAME,
                "authPassword": config.A1MOBILE_SIP_PASSWORD,
            },
        },
    )


def create_phone_number(credential_id: str) -> dict:
    """Attach the claimed a1mobile number to the trunk so it's usable as the
    outbound caller ID."""
    return _post(
        "/phone-number",
        {
            "provider": "byo-phone-number",
            "name": "a1mobile-number",
            "number": config.A1MOBILE_PHONE_NUMBER,
            "numberE164CheckEnabled": False,
            "credentialId": credential_id,
        },
    )


def _assistant_body() -> dict:
    """Assistant definition. Tools are declared inline pointing at our webhook,
    so the negotiation logic stays in server/agent/tools.py rather than being
    duplicated in Vapi."""
    if not config.PUBLIC_BASE_URL:
        raise SystemExit("PUBLIC_BASE_URL is not set in .env (needed so Vapi can reach the tool webhook)")

    tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": {
                    "type": "object",
                    "properties": t["properties"],
                    "required": t["required"],
                },
            },
            "server": {"url": f"{config.PUBLIC_BASE_URL}/api/vapi/tools"},
        }
        for t in TOOL_DEFS
    ]

    return {
        "name": "SettleWise collections agent",
        "firstMessage": "Hello, this is SettleWise calling about your account. Am I speaking with the account holder?",
        # A live phone call can't tolerate the dead air of several sequential
        # tool round-trips before the agent speaks - the first attempt died to
        # silence-timed-out mid-sentence. Give it room, and see the voice-call
        # override in the system prompt below.
        "silenceTimeoutSeconds": 60,
        "responseDelaySeconds": 0.2,
        "model": {
            "provider": "openai",
            "model": "gpt-4.1",
            "messages": [
                {
                    "role": "system",
                    # {{debt_id}} plus the pre-loaded facts are filled per-call
                    # via assistantOverrides.variableValues.
                    "content": SYSTEM_PROMPT
                    + "\n\n## This call (voice - read this carefully)\n"
                    "You are on a live phone call with the borrower for debt_id {{debt_id}}.\n\n"
                    "Their current details have ALREADY been fetched for you:\n"
                    "{{debt_context}}\n\n"
                    "Because those facts are above, do NOT call get_debt_profile, get_memory, "
                    "get_policy, or check_call_allowed at the start of this call - you already "
                    "have everything you need to greet them and state the amount due. Speak "
                    "first, immediately.\n\n"
                    "VOICE RULES (these override the step-by-step flow above):\n"
                    "- Never say 'hold on', 'one moment', or 'let me check'. Dead air ends the call.\n"
                    "- Keep every turn to one or two short sentences, then stop and let them reply.\n"
                    "- Only call a tool when you are about to CHANGE something (send a payment "
                    "link, schedule a reminder, record the outcome, write memory, escalate) or "
                    "when you need offer options you don't already have.\n"
                    "- Say the numbers naturally: 'four hundred and twenty dollars', not '420.0'.",
                }
            ],
            "tools": tools,
        },
    }


def create_assistant() -> dict:
    return _post("/assistant", _assistant_body())


def update_assistant(assistant_id: str) -> dict:
    """Re-push the assistant definition after editing prompt.md or the tool
    registry, without recreating (and re-id-ing) the assistant."""
    return _patch(f"/assistant/{assistant_id}", _assistant_body())


def _debt_context(debt_id: str) -> str:
    """Pre-fetch the facts the agent would otherwise open the call by looking
    up. Four sequential tool round-trips before the first sentence is fine in
    text but produces call-killing dead air on a live phone line, so we inline
    the results instead."""
    from .agent import tools as agent_tools

    debt = agent_tools.get_debt_profile(debt_id)
    if "error" in debt:
        return f"(no debt found for {debt_id})"
    policy = agent_tools.get_policy()
    memory = agent_tools.get_memory(debt_id).get("memory", [])
    eligibility = agent_tools.check_call_allowed(debt_id)

    remaining = debt["amount_due"] - debt["amount_collected"]
    lines = [
        f"- Borrower name: {debt['name']}",
        f"- Total owed: ${debt['amount_due']:g} (already collected ${debt['amount_collected']:g}, "
        f"still outstanding ${remaining:g})",
        f"- Due date: {debt['due_date']}, breach date: {debt['breach_date']}",
        f"- Account status: {debt['status']}",
        f"- Salary date on file: {debt['salary_date'] or 'unknown'}",
        f"- Last call summary: {debt['last_call_summary'] or '(no prior calls)'}",
        f"- Contact allowed right now: {eligibility['allowed']} ({eligibility['reason']})",
        f"- Policy: max discount {policy['max_discount_percent']:g}%, "
        f"min payment today {policy['min_payment_today_percent']:g}% of outstanding, "
        f"up to {policy['max_installments']} installments",
    ]
    if memory:
        facts = "; ".join(f"{m['key']}={m['value']}" for m in memory)
        lines.append(f"- Remembered about them: {facts}")
    return "\n".join(lines)


def place_call(to_number: str, debt_id: str | None = None) -> dict:
    payload = {
        "phoneNumberId": config.VAPI_PHONE_NUMBER_ID,
        "assistantId": config.VAPI_ASSISTANT_ID,
        "customer": {"number": to_number},
    }
    if debt_id:
        # Sent via variableValues rather than a model override - Vapi rejects a
        # partial model object, and the assistant prompt references these.
        payload["assistantOverrides"] = {
            "variableValues": {"debt_id": debt_id, "debt_context": _debt_context(debt_id)}
        }
    return _post("/call", payload)


def _append_env(values: dict):
    lines = [f"{k}={v}" for k, v in values.items()]
    with open(config.BASE_DIR / ".env", "a") as f:
        f.write("\n# Vapi (outbound calling)\n" + "\n".join(lines) + "\n")
    print("\nWrote to .env:")
    for line in lines:
        print(" ", line)


def setup():
    print("Creating SIP trunk credential...")
    cred = create_sip_trunk()
    print("  credential id:", cred["id"])

    print("Attaching phone number", config.A1MOBILE_PHONE_NUMBER, "...")
    number = create_phone_number(cred["id"])
    print("  phone number id:", number["id"])

    print("Creating assistant with", len(TOOL_DEFS), "tools ->", f"{config.PUBLIC_BASE_URL}/api/vapi/tools")
    assistant = create_assistant()
    print("  assistant id:", assistant["id"])

    _append_env(
        {
            "VAPI_CREDENTIAL_ID": cred["id"],
            "VAPI_PHONE_NUMBER_ID": number["id"],
            "VAPI_ASSISTANT_ID": assistant["id"],
        }
    )
    print("\nSetup complete. Place a call with:")
    print("  .venv/bin/python -m server.vapi_setup call +1YOURNUMBER debt_002")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "setup":
        setup()
    elif cmd == "update":
        print(json.dumps({"id": update_assistant(config.VAPI_ASSISTANT_ID)["id"], "updated": True}, indent=2))
    elif cmd == "call":
        to = sys.argv[2]
        debt_id = sys.argv[3] if len(sys.argv) > 3 else None
        print(json.dumps(place_call(to, debt_id), indent=2))
    else:
        print("Usage: python -m server.vapi_setup {setup | update | call <+1NUMBER> [debt_id]}")
