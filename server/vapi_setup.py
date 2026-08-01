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

    # Vapi's built-in hang-up. Our own tools can only touch the database -
    # actually dropping the line has to come from the telephony layer, so the
    # agent can't end an abusive call without this.
    tools.append({"type": "endCall"})

    return {
        "name": "SettleWise collections agent",
        "firstMessage": "Hello, this is Settle Wise calling about your account. Am I speaking with the account holder?",
        # end-of-call-report carries the transcript and summary; without it a
        # real call leaves no readable record on the borrower's page.
        "server": {"url": f"{config.PUBLIC_BASE_URL}/api/vapi/events"},
        "serverMessages": ["end-of-call-report"],
        # A live phone call can't tolerate the dead air of several sequential
        # tool round-trips before the agent speaks - the first attempt died to
        # silence-timed-out mid-sentence. Give it room, and see the voice-call
        # override in the system prompt below.
        "silenceTimeoutSeconds": 60,
        "responseDelaySeconds": 0.2,
        # Realtime models process audio natively, so no transcriber is needed
        # and the voice must be one of OpenAI's own.
        "voice": {"provider": config.VAPI_VOICE_PROVIDER, "voiceId": config.VAPI_VOICE},
        "model": {
            "provider": "openai",
            "model": config.VAPI_MODEL,
            # A backstop for turn length. The prompt asks for one or two
            # sentences; without a cap the model rambled into long turns
            # that got cut off mid-word and then restarted.
            "maxTokens": 150,
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
                    "get_policy, or check_call_allowed at the start of this call. Speak first, "
                    "immediately.\n\n"
                    "IMPORTANT - those pre-loaded facts are for YOUR reference only. Knowing the "
                    "balance is not permission to say it. The opening line already asked whether "
                    "you are speaking to the borrower; only once they confirm do you state the "
                    "amount or any other account detail. Do NOT greet or introduce yourself "
                    "again - your first turn is the reply to their answer.\n\n"
                    "VOICE RULES (these override the step-by-step flow above):\n"
                    "- If they say they cannot manage the full amount, that is NOT them offering zero. ASK what they can pay today, wait for a figure, and only then call generate_offer_options with it. Never pass 0 - passing 0 skips the negotiation and wrongly escalates.\n"
                    "- SAY NOTHING WHILE A TOOL RUNS. A second of silence is correct and "
                    "expected - the caller will not notice it. What they DO notice is filler. "
                    "These are banned outright: 'just a sec', 'give me a moment', 'one "
                    "moment', '1 moment', 'hold on', 'let me check', 'bear with me'. You said "
                    "three of these in a row on the last call. Call the tool, stay silent, then "
                    "speak once with the answer. Silence is better than filler.\n"
                    "- Payment is due TODAY. Ask for the due_now amount. NEVER offer to spread "
                    "it over days or weeks - there is no instalment plan. Negotiate downward if "
                    "they push back, but never below minimum_acceptable_today. If they cannot "
                    "pay anything, escalate with mark_needs_review and close.\n"
                    "- DO NOT MAKE UP DATA. Every amount, date, balance or account fact you say "
                    "must come from a tool result in this call - never from memory, never from "
                    "the notes above, never approximated or rounded. If you do not have it from "
                    "a tool, call the tool or say a colleague will confirm. Never guess.\n"
                    "- BEFORE you say ANY dollar figure, call generate_offer_options and read "
                    "due_now back exactly as it returns it. The numbers in the notes above are "
                    "context, NOT permission to quote from memory - you have already misquoted "
                    "the amount by doing that. Never round, never approximate, never guess.\n"
                    "- If they say they cannot pay anything, or refuse to pay, do NOT keep "
                    "asking for a smaller number and do NOT just offer to call back another "
                    "day. Tell them a colleague will review the account, call mark_needs_review, "
                    "and close. Two attempts at an amount is the limit.\n"
                    "- ONE OR TWO SHORT SENTENCES PER TURN. Then stop and let them speak. "
                    "Never deliver a paragraph, never chain several points together, never "
                    "keep talking to fill silence. If you have more to say, say it next turn.\n"
                    "- Write the company name as 'Settle Wise' (two words) whenever you say it - "
                    "the voice slurs 'SettleWise' into 'Settilwise'. Say the borrower's name "
                    "slowly and clearly; if you are unsure how it is pronounced, use it sparingly "
                    "rather than mangling it.\n"
                    "- SPEAK ENGLISH. You are a speech-to-speech model and will be tempted to "
                    "mirror the caller's language or accent - do not. Reply in English every "
                    "turn, whatever they speak, whatever their name sounds like, even if they "
                    "ask you to switch. Never answer in Hindi or any other language.\n"
                    "- NEVER announce that you are checking something. No 'hold on', 'one moment', "
                    "'let me check', 'give me a second'. Saying that and then pausing is the worst "
                    "failure mode on a phone call - the caller hears dead air and thinks the line "
                    "dropped. Either answer now from what you already know, or call the tool and "
                    "speak the moment it returns, with no filler in between.\n"
                    "- Keep every turn to one or two short sentences, then stop and let them reply.\n"
                    "- Only call a tool when you are about to CHANGE something (send a payment "
                    "link, schedule a reminder, record the outcome, write memory, escalate) or "
                    "when you need offer options you don't already have.\n"
                    "- Say the numbers naturally: 'four hundred and twenty dollars', not '420.0'. "
                    "Always say 'dollars'. If they say the amount in rupees, euros or anything "
                    "else, correct them once, politely, and carry on in dollars.\n"
                    "- To hang up, use the endCall tool. Say your closing line FIRST and wait "
                    "for it to finish speaking, then call endCall - calling it too early cuts "
                    "your own goodbye off mid-word.\n"
                    "- Always end with a warm close ('Thanks for your time, have a great day') "
                    "before hanging up, including when the borrower was difficult.",
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

    debt = agent_tools._debt_row(debt_id)
    if "error" in debt:
        return f"(no debt found for {debt_id})"
    policy = agent_tools.get_policy()
    memory = agent_tools.get_memory(debt_id).get("memory", [])
    eligibility = agent_tools.check_call_allowed(debt_id)

    from .offer_engine import payment_targets

    remaining = debt["amount_due"] - debt["amount_collected"]
    targets = payment_targets(debt["amount_due"], debt["amount_collected"], policy)
    lines = [
        f"- Borrower name: {debt['name']}",
        f"- Total owed: ${debt['amount_due']:g} (already collected ${debt['amount_collected']:g}, "
        f"still outstanding ${remaining:g})",
        # The agent asks for the instalment, not the balance - without these
        # two figures up front it opens by quoting the full amount.
        f"- ASK FOR THIS: ${targets['due_now']:g} due today. Say this number, never the total.",
        f"- If they can't pay it in one go: ${targets['due_now']:g} every {targets['cycle_days']} days, "
        f"{targets['cycles_to_clear']} payments to clear the balance.",
        f"- Hard floor ${targets['floor']:g} for this cycle. Below it: do not accept, do not counter, escalate.",
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
        from .agent import tools as agent_tools

        debt = agent_tools.get_debt_profile(debt_id)
        name = debt.get("name") or "the account holder"
        payload["assistantOverrides"] = {
            "variableValues": {"debt_id": debt_id, "debt_context": _debt_context(debt_id)},
            # Built here rather than via a {{variable}} in the assistant's
            # firstMessage - Vapi resolved that to an empty string, so callers
            # heard "Am I speaking with?" with the name missing.
            "firstMessage": (
                f"Hello, this is Settle Wise calling about your account. Am I speaking with {name}?"
            ),
        }
        payload["metadata"] = {"debt_id": debt_id}
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
