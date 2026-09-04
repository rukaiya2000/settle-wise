"""Voice pipeline for the in-browser call (server/routes/browser_call.py).

Uses OpenAI's realtime speech-to-speech model with the same SYSTEM_PROMPT
and TOOL_DEFS as every other path, so a browser session and a phone call
exercise identical tools against the same database.
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
from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService
from pipecat.workers.runner import WorkerRunner

from .. import config
from . import SYSTEM_PROMPT
from .tool_registry import TOOL_DEFS


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


async def run_bot_webrtc(webrtc_connection, debt_id: str | None) -> None:
    """Browser-call entry point (server/routes/browser_call.py's /api/offer).

    A live mic/speaker session straight from the browser to the realtime
    agent - "the agent calls me" without a phone number involved.
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
