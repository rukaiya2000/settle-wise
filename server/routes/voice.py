"""a1mobile voice webhook + media-stream endpoint.

a1mobile's SIP trunk runs on sip.telnyx.com, and "we stream the call to you"
matches Telnyx's own webhook contract: they POST here to start the call, we
answer with TeXML pointing a <Stream> at our /ws endpoint, and they open a
WebSocket carrying the audio. This has NOT been confirmed against a1mobile's
own docs (only their curl examples), so the first real test call should be
watched in the server logs - if the handshake doesn't match, the raw payload
gets logged for adjustment (see the fallback branch below).
"""

import uuid

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import Response
from loguru import logger

from .. import config
from ..agent.pipeline import run_bot

router = APIRouter()


@router.post("/voice")
async def voice_webhook(request: Request):
    body = await request.body()
    logger.info(f"a1mobile voice webhook hit: {body!r}")

    ws_url = f"wss://{config.PUBLIC_BASE_URL.replace('https://', '').replace('http://', '')}/ws"
    texml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{ws_url}" bidirectionalMode="rtp"></Stream>
  </Connect>
  <Pause length="40"/>
</Response>"""
    return Response(content=texml, media_type="application/xml")


@router.websocket("/ws")
async def voice_media_stream(websocket: WebSocket):
    await websocket.accept()
    logger.info("Voice media stream connected")

    from pipecat.runner.types import WebSocketRunnerArguments

    runner_args = WebSocketRunnerArguments(websocket=websocket, session_id=str(uuid.uuid4()))
    await run_bot(runner_args)
