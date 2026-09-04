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
from pipecat.runner.utils import create_transport, parse_telephony_websocket
from pipecat.serializers.telnyx import TelnyxFrameSerializer
from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.workers.runner import WorkerRunner

from .. import config
from ..db import get_conn
from . import SYSTEM_PROMPT
from .tool_registry import TOOL_DEFS


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
            name=t["name"],
            description=t["description"],
            properties=t["properties"],
            required=t["required"],
            handler=_make_handler(t["fn"]),
        )
        for t in TOOL_DEFS
    ]
    return ToolsSchema(standard_tools=schemas)


async def run_bot(runner_args: WebSocketRunnerArguments) -> None:
    # create_transport()'s telnyx convenience path builds a TelnyxFrameSerializer
    # with auto_hang_up=True by default, which requires a real Telnyx api_key/
    # call_control_id to hang up via Telnyx's REST API on call end. We don't
    # have Telnyx credentials - a1mobile owns the underlying Telnyx call and
    # tears it down itself - so that serializer construction raises ValueError
    # before any audio flows (confirmed live: call connects, then dead silence).
    # Build the transport manually instead, with auto_hang_up disabled.
    transport_type, call_data = await parse_telephony_websocket(runner_args.websocket)

    if transport_type == "telnyx":
        serializer = TelnyxFrameSerializer(
            stream_id=call_data["stream_id"],
            call_control_id=call_data["call_id"],
            outbound_encoding=call_data["outbound_encoding"],
            inbound_encoding="PCMU",
            params=TelnyxFrameSerializer.InputParams(auto_hang_up=False),
        )
    else:
        # Other providers' serializers don't hard-validate at construction
        # time the way Telnyx's does, so create_transport's normal path is
        # safe to reuse here.
        runner_args.transport_type = transport_type
        runner_args.call_data = call_data
        transport_params = {
            "twilio": lambda: FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True),
            "plivo": lambda: FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True),
            "exotel": lambda: FastAPIWebsocketParams(audio_in_enabled=True, audio_out_enabled=True),
        }
        transport = await create_transport(runner_args, transport_params)
        caller_phone = getattr(call_data, "from_number", None)
        debt_id = _find_debt_id_by_phone(caller_phone)
        return await _run_pipeline(transport, debt_id)

    transport = FastAPIWebsocketTransport(
        websocket=runner_args.websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True, audio_out_enabled=True, add_wav_header=False, serializer=serializer
        ),
    )
    caller_phone = getattr(call_data, "from_number", None)
    debt_id = _find_debt_id_by_phone(caller_phone)
    return await _run_pipeline(transport, debt_id)


async def run_bot_webrtc(webrtc_connection, debt_id: str | None) -> None:
    """Browser-call entry point (server/routes/browser_call.py's /api/offer).

    a1mobile has no outbound-calling capability at all (confirmed by querying
    its MCP tool catalog directly: claim_number, point_number, send SMS,
    verify - no dial/call tool exists). This is the substitute for "the
    agent calls me": a live mic/speaker session straight from the browser to
    the same realtime agent, no phone number involved.
    """
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True),
    )
    await _run_pipeline(transport, debt_id)


async def _run_pipeline(transport, debt_id: str | None) -> None:
    # Realtime service handles STT, LLM, and TTS internally over one
    # WebSocket to OpenAI - no separate STT/TTS services needed.
    llm = OpenAIRealtimeLLMService(
        api_key=config.OPENAI_REALTIME_API_KEY,
        model=config.OPENAI_REALTIME_MODEL,
    )

    opening_note = (
        f"The caller's debt_id is {debt_id}. Use get_debt_profile to confirm details before saying any amount."
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
