"""Browser-based voice call - the substitute for outbound calling.

a1mobile has no outbound-calling capability (confirmed via its MCP tool
catalog: claim_number, point_number, send_confirmation_sms,
request/confirm_number_verification - no dial/call tool exists anywhere).
This exposes Pipecat's SmallWebRTC signaling endpoint so a browser tab can
open a live mic/speaker session straight to the same realtime agent used for
real a1mobile calls - no phone number needed.
"""

from fastapi import APIRouter, BackgroundTasks
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.request_handler import (
    IceCandidate,
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

from ..agent.pipeline import run_bot_webrtc

router = APIRouter()
_handler = SmallWebRTCRequestHandler()


@router.post("/api/offer")
async def offer(body: dict, background_tasks: BackgroundTasks):
    request = SmallWebRTCRequest.from_dict(body)
    debt_id = (request.request_data or {}).get("debt_id") if request.request_data else None

    async def webrtc_connection_callback(connection: SmallWebRTCConnection):
        background_tasks.add_task(run_bot_webrtc, connection, debt_id)

    return await _handler.handle_web_request(request=request, webrtc_connection_callback=webrtc_connection_callback)


@router.patch("/api/offer")
async def offer_ice_candidate(body: dict):
    request = SmallWebRTCPatchRequest(
        pc_id=body["pc_id"],
        candidates=[IceCandidate(**c) for c in body["candidates"]],
    )
    await _handler.handle_patch_request(request)
    return {"status": "success"}
