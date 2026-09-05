"""Text-based ReAct tester for the negotiation agent - no phone call needed.

Runs the exact same prompt (server/agent/prompt.md) and tools
(server/agent/tool_registry.py, backed by server/agent/tools.py) as the live
realtime voice pipeline, over plain OpenAI chat completions instead of a
WebSocket audio stream. Each turn shows the explicit ReAct trace: every tool
call the model makes (Action) and what it got back (Observation) before its
reply (the "Reason" step is the model's private planning and isn't printed,
same as it wouldn't be spoken aloud on a real call).

Usage:
    .venv/bin/python -m server.agent.console debt_002
"""

import json
import sys

from .. import config, llm
from ..vapi_setup import _debt_context
from . import SYSTEM_PROMPT
from .tool_registry import TOOL_DEFS

TOOLS_BY_NAME = {t["name"]: t for t in TOOL_DEFS}


def _to_openai_tools() -> list[dict]:
    return [
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
        }
        for t in TOOL_DEFS
    ]


def run_console(debt_id: str, model: str | None = None):
    model = model or config.OPENAI_CHAT_MODEL
    client = llm.chat_client()
    tools = _to_openai_tools()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            # The same context block the Vapi assistant gets. Without it the
            # model has to open the call before it has looked anything up, and
            # greets the borrower with a literal "{borrower's name}".
            "role": "system",
            "content": (
                f"The caller's debt_id is {debt_id}. Use get_debt_profile to confirm details "
                f"before saying any amount.\n{_debt_context(debt_id)}"
            ),
        },
        {"role": "user", "content": "(the phone just connected, start the call)"},
    ]

    print(f"--- ReAct console: negotiating {debt_id} (model={model}) ---")
    print("Type as the borrower. Ctrl-C to quit.\n")

    while True:
        response = client.chat.completions.create(model=model, messages=messages, tools=tools)
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        if message.tool_calls:
            for call in message.tool_calls:
                name = call.function.name
                args = json.loads(call.function.arguments or "{}")
                tool = TOOLS_BY_NAME.get(name)
                result = tool["fn"](**args) if tool else {"error": f"unknown tool {name}"}
                print(f"  [Action] {name}({args})")
                print(f"  [Observation] {result}\n")
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)}
                )
            continue  # let the model react to the observations before speaking

        if message.content:
            print(f"Agent: {message.content}\n")

        try:
            borrower_line = input("Borrower: ")
        except (EOFError, KeyboardInterrupt):
            print("\n--- call ended ---")
            break
        messages.append({"role": "user", "content": borrower_line})


if __name__ == "__main__":
    debt_id = sys.argv[1] if len(sys.argv) > 1 else "debt_002"
    run_console(debt_id)
