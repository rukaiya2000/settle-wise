"""Single source of truth for the agent's tool surface (name, description,
JSON schema, and implementation) so the live realtime voice pipeline
(server/agent/pipeline.py) and the text-based ReAct console
(server/agent/console.py) share identical tool behavior - a scheduled
replay, a text test, and a real phone call all call the exact same
functions in server/agent/tools.py.
"""

from . import tools as agent_tools

TOOL_DEFS = [
    {
        "name": "get_debt_profile",
        "description": "Fetch amount due, amount collected/promised, dates, and status for a debt by id.",
        "properties": {"debt_id": {"type": "string"}},
        "required": ["debt_id"],
        "fn": agent_tools.get_debt_profile,
    },
    {
        "name": "get_memory",
        "description": "Get facts previously learned about this borrower (salary date, call preference, prior promises, etc).",
        "properties": {"debt_id": {"type": "string"}},
        "required": ["debt_id"],
        "fn": agent_tools.get_memory,
    },
    {
        "name": "get_payment_history",
        "description": (
            "What has actually been sent and paid on this account: every SMS payment link, its "
            "status, and how much has been collected. Call this before responding to "
            "\"I already paid\" or \"you never sent me anything\" - do not take either claim at "
            "face value, and do not contradict the borrower without checking first."
        ),
        "properties": {"debt_id": {"type": "string"}},
        "required": ["debt_id"],
        "fn": agent_tools.get_payment_history,
    },
    {
        "name": "get_policy",
        "description": "Get the collections policy (max discount, min payment-today percent, max installments, allowed call hours).",
        "properties": {},
        "required": [],
        "fn": agent_tools.get_policy,
    },
    {
        "name": "check_call_allowed",
        "description": "Check whether it is allowed to discuss this debt with the borrower right now.",
        "properties": {"debt_id": {"type": "string"}},
        "required": ["debt_id"],
        "fn": agent_tools.check_call_allowed,
    },
    {
        "name": "generate_offer_options",
        "description": (
            "Get the approved repayment options. Returns due_now (the instalment due this cycle - "
            "ask for this, NOT the whole balance), minimum_acceptable_today (a hard floor), and "
            "below_floor. If below_floor is true the offer list is empty: do not accept, do not "
            "counter, stop negotiating and call mark_needs_review. Pass borrower_can_pay_today "
            "whenever they name an amount."
        ),
        "properties": {
            "debt_id": {"type": "string"},
            "borrower_can_pay_today": {"type": "number"},
        },
        "required": ["debt_id"],
        "fn": agent_tools.generate_offer_options,
    },
    {
        "name": "apply_discount",
        "description": "Check whether a requested discount percentage is within policy and get the settled amount.",
        "properties": {
            "debt_id": {"type": "string"},
            "requested_pct": {"type": "number", "description": "Discount percentage requested, e.g. 10 for 10%"},
        },
        "required": ["debt_id", "requested_pct"],
        "fn": agent_tools.apply_discount,
    },
    {
        "name": "record_call_event",
        "description": "Log the outcome of this call before ending it.",
        "properties": {
            "debt_id": {"type": "string"},
            "outcome": {
                "type": "string",
                "enum": ["answered", "no_answer", "callback_requested", "promised", "paid", "needs_review"],
            },
            "summary": {"type": "string"},
            "amount_promised": {
                "type": "number",
                "description": "Total amount still owed and committed to, not yet collected - "
                "e.g. if the borrower agreed to 200 today and 220 later, pass 420, not 200.",
            },
            "promise_date": {"type": "string", "description": "When the LAST installment of amount_promised is due, if any is deferred."},
        },
        "required": ["debt_id", "outcome", "summary"],
        "fn": agent_tools.record_call_event,
    },
    {
        "name": "send_sms_payment_link",
        "description": "Create a payment link for an agreed amount and send it to the borrower.",
        "properties": {
            "debt_id": {"type": "string"},
            "amount": {"type": "number"},
            "reason": {"type": "string"},
        },
        "required": ["debt_id", "amount"],
        "fn": agent_tools.send_sms_payment_link,
    },
    {
        "name": "send_sms",
        "description": (
            "Text the borrower right now, during the call - for example to confirm in writing "
            "what was just agreed, or to send details they asked to have in writing. "
            "Sends immediately to their real phone. Use send_sms_payment_link instead when the "
            "message is a payment link, and schedule_sms_reminder to book one for later."
        ),
        "properties": {
            "debt_id": {"type": "string"},
            "body": {
                "type": "string",
                "description": "The message text. Keep it to one or two short, professional sentences.",
            },
        },
        "required": ["debt_id", "body"],
        "fn": agent_tools.send_sms_now,
    },
    {
        "name": "schedule_sms_reminder",
        "description": "Book a future SMS reminder for an unpaid payment link.",
        "properties": {
            "debt_id": {"type": "string"},
            "send_at": {"type": "string", "description": "ISO 8601 datetime"},
            "message_type": {"type": "string"},
        },
        "required": ["debt_id", "send_at"],
        "fn": agent_tools.schedule_sms_reminder,
    },
    {
        "name": "schedule_next_action",
        "description": "Schedule the next workflow action for this debt (e.g. a follow-up call at a specific time).",
        "properties": {
            "debt_id": {"type": "string"},
            "next_action": {"type": "string"},
            "next_action_at": {"type": "string", "description": "ISO 8601 datetime"},
            "reason": {"type": "string"},
        },
        "required": ["debt_id", "next_action", "next_action_at"],
        "fn": agent_tools.schedule_next_action,
    },
    {
        "name": "update_debt_status",
        "description": "Update the debt's status and/or next action.",
        "properties": {
            "debt_id": {"type": "string"},
            "status": {"type": "string"},
            "last_call_summary": {"type": "string"},
            "next_action": {"type": "string"},
            "next_action_at": {"type": "string"},
        },
        "required": ["debt_id", "status"],
        "fn": agent_tools.update_debt_status,
    },
    {
        "name": "write_memory",
        "description": "Save a structured, explainable fact learned about the borrower (e.g. salary_date, call_preference, no_contact).",
        "properties": {
            "debt_id": {"type": "string"},
            "key": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["debt_id", "key", "value"],
        "fn": agent_tools.write_memory,
    },
    {
        "name": "flag_borrower",
        "description": (
            "Record a conduct problem on the borrower's profile - abuse, threats, or flat refusal "
            "to engage after warnings - so whoever picks this up next sees it before dialling. "
            "Use severity 'warning' to note it while keeping the account collectable, or 'abuse' "
            "to also suspend automated collection and route to human review."
        ),
        "properties": {
            "debt_id": {"type": "string"},
            "reason": {"type": "string", "description": "Factual description of what happened. No judgement or insults."},
            "severity": {"type": "string", "enum": ["warning", "abuse"]},
        },
        "required": ["debt_id", "reason"],
        "fn": agent_tools.flag_borrower,
    },
    {
        "name": "mark_needs_review",
        "description": "Stop collection and escalate this debt to human review (dispute, fraud, wrong party, hardship, low confidence, abusive borrower, out-of-policy settlement).",
        "properties": {
            "debt_id": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["debt_id", "reason"],
        "fn": agent_tools.mark_needs_review,
    },
]
