"""Voice pipeline wiring for a live call streamed to us over a1mobile.

a1mobile's SIP trunk is hosted at sip.telnyx.com, and its webhook flow
("we stream the call to you") mirrors Telnyx's own Media Streaming handshake,
which Pipecat has first-class support for. server/routes/voice.py hands the
raw FastAPI WebSocket to run_bot() below; create_transport() auto-detects the
provider from the first handshake messages and builds the right serializer,
so this also works unmodified if a1mobile's stream turns out to be
Twilio/Plivo/Exotel-shaped instead.

Uses OpenAI's realtime speech-to-speech model (direct API key, not the
hackathon gateway - that gateway is an HTTP-only Lambda Function URL and
can't proxy the realtime WebSocket API), so there's no separate STT/TTS
service in this pipeline.
"""

from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import WebSocketRunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from pipecat.workers.runner import WorkerRunner

from .. import config
from ..db import get_conn
from . import tools as agent_tools
from .prompt import SYSTEM_PROMPT


def _find_debt_id_by_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM debts WHERE phone = ?", (phone,)).fetchone()
    return row["id"] if row else None


def _make_handler(fn):
    async def handler(params):
        result = fn(**params.arguments)
        await params.result_callback(result)

    return handler


def _build_tools_schema() -> ToolsSchema:
    schemas = [
        FunctionSchema(
            name="get_debt",
            description="Fetch amount due, dates, and status for a debt by id.",
            properties={"debt_id": {"type": "string"}},
            required=["debt_id"],
            handler=_make_handler(agent_tools.get_debt),
        ),
        FunctionSchema(
            name="check_contact_eligibility",
            description="Check whether it is allowed to discuss this debt with the borrower right now.",
            properties={"debt_id": {"type": "string"}},
            required=["debt_id"],
            handler=_make_handler(agent_tools.check_contact_eligibility),
        ),
        FunctionSchema(
            name="generate_offer_ladder",
            description="Get the approved repayment offers for this debt, in priority order.",
            properties={"debt_id": {"type": "string"}},
            required=["debt_id"],
            handler=_make_handler(agent_tools.generate_offer_ladder),
        ),
        FunctionSchema(
            name="apply_discount",
            description="Check whether a requested discount percentage is within policy and get the settled amount.",
            properties={
                "debt_id": {"type": "string"},
                "requested_pct": {"type": "number", "description": "Discount percentage requested, e.g. 10 for 10%"},
            },
            required=["debt_id", "requested_pct"],
            handler=_make_handler(agent_tools.apply_discount),
        ),
        FunctionSchema(
            name="create_payment_link",
            description="Create a payment link for an agreed amount and send it to the borrower.",
            properties={
                "debt_id": {"type": "string"},
                "amount": {"type": "number"},
            },
            required=["debt_id", "amount"],
            handler=_make_handler(agent_tools.create_payment_link),
        ),
        FunctionSchema(
            name="schedule_followup",
            description="Schedule the next action/reminder for this debt.",
            properties={
                "debt_id": {"type": "string"},
                "next_action_at": {"type": "string", "description": "ISO 8601 datetime"},
                "next_action": {"type": "string"},
            },
            required=["debt_id", "next_action_at", "next_action"],
            handler=_make_handler(agent_tools.schedule_followup),
        ),
        FunctionSchema(
            name="write_memory",
            description="Save a structured, explainable fact learned about the borrower (e.g. salary_date, call_preference, no_contact).",
            properties={
                "debt_id": {"type": "string"},
                "key": {"type": "string"},
                "value": {"type": "string"},
            },
            required=["debt_id", "key", "value"],
            handler=_make_handler(agent_tools.write_memory),
        ),
        FunctionSchema(
            name="mark_dispute",
            description="Stop collection and flag this debt as disputed by the borrower.",
            properties={
                "debt_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            required=["debt_id", "reason"],
            handler=_make_handler(agent_tools.mark_dispute),
        ),
        FunctionSchema(
            name="escalate_human_review",
            description="Escalate this debt to human review (fraud, hardship, wrong party, low confidence, abusive borrower, out-of-policy settlement).",
            properties={
                "debt_id": {"type": "string"},
                "trigger": {"type": "string"},
                "reasoning": {"type": "string"},
            },
            required=["debt_id", "trigger", "reasoning"],
            handler=_make_handler(agent_tools.escalate_human_review),
        ),
        FunctionSchema(
            name="record_call_outcome",
            description="Log the outcome of this call before ending it.",
            properties={
                "debt_id": {"type": "string"},
                "outcome": {
                    "type": "string",
                    "enum": ["answered", "no_answer", "callback", "promised", "paid", "needs_review"],
                },
                "summary": {"type": "string"},
                "amount_promised": {"type": "number"},
                "promise_date": {"type": "string"},
            },
            required=["debt_id", "outcome", "summary"],
            handler=_make_handler(agent_tools.record_call_outcome),
        ),
    ]
    return ToolsSchema(standard_tools=schemas)


async def run_bot(runner_args: WebSocketRunnerArguments) -> None:
    transport_params = {
        "telnyx": lambda: FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True),
        "twilio": lambda: FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True),
        "plivo": lambda: FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True),
        "exotel": lambda: FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True),
    }
    transport = await create_transport(runner_args, transport_params)

    call_data = getattr(runner_args, "call_data", None)
    caller_phone = getattr(call_data, "from_number", None) if call_data else None
    debt_id = _find_debt_id_by_phone(caller_phone)

    # Realtime service handles STT, LLM, and TTS internally over one
    # WebSocket to OpenAI - no separate STT/TTS services needed.
    llm = OpenAIRealtimeLLMService(
        api_key=config.OPENAI_REALTIME_API_KEY,
        model=config.OPENAI_REALTIME_MODEL,
    )

    opening_note = (
        f"The caller's debt_id is {debt_id}. Use get_debt to confirm details before saying any amount."
        if debt_id
        else "The caller's debt_id is unknown. Ask for their name and confirm identity before discussing any debt."
    )

    context = LLMContext(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": opening_note},
        ],
        tools=_build_tools_schema(),
    )
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            user_aggregator,
            llm,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Call connected (debt_id={debt_id})")
        context.add_message({"role": "developer", "content": "Greet the borrower and start the call now."})
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Call disconnected")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await runner.run()
