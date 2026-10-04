import os
import json
import base64
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Dial, Start

from backend.db import (
    get_senior_by_twilio_number,
    upsert_caller_number,
    insert_call,
    update_call_status,
    complete_call,
    get_call_by_sid,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("trot.voice")

app = FastAPI(title="TROT Backend", version="0.1.0")

# In-memory call state cache for low-latency lookups
call_states: Dict[str, Dict[str, Any]] = {}


def get_public_base_url(request: Request) -> str:
    """Returns the base public URL, prioritizing PUBLIC_BASE_URL env var."""
    base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if base_url:
        return base_url

    # Fallback to forwarded headers or request URL
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    forwarded_host = request.headers.get("x-forwarded-host", request.url.netloc)
    return f"{forwarded_proto}://{forwarded_host}".rstrip("/")


def get_public_ws_url(request: Request) -> str:
    """Returns the public wss:// URL for the media stream."""
    base_url = get_public_base_url(request)
    if base_url.startswith("https://"):
        return f"wss://{base_url[8:]}/ws/audio"
    elif base_url.startswith("http://"):
        return f"ws://{base_url[7:]}/ws/audio"
    else:
        return f"wss://{base_url}/ws/audio"


def set_active_call_status(call_sid: str, status: str) -> None:
    """Updates in-memory cache and persists status to database."""
    if call_sid not in call_states:
        call_states[call_sid] = {}
    call_states[call_sid]["status"] = status
    try:
        update_call_status(call_sid, status)
    except Exception as e:
        logger.warning(f"Failed to update call status for {call_sid} in DB: {e}")


def get_active_call_status(call_sid: str) -> Optional[str]:
    """Gets call status with in-memory fast-path and DB fallback."""
    if call_sid in call_states and "status" in call_states[call_sid]:
        return call_states[call_sid]["status"]

    try:
        call = get_call_by_sid(call_sid)
        if call:
            status = call.get("status")
            if call_sid not in call_states:
                call_states[call_sid] = {}
            call_states[call_sid]["status"] = status
            return status
    except Exception as e:
        logger.warning(f"Failed to fetch call status for {call_sid} from DB: {e}")

    return None


@app.get("/health")
def health():
    return {"status": "ok", "app": "TROT"}


@app.post("/voice")
@app.post("/twilio/voice")
async def handle_voice(request: Request):
    """
    Twilio voice webhook for incoming calls.
    Lookup senior by To number, log call record, starts media stream, and dials senior
    with dial-status and dial-complete callbacks.
    """
    # TODO: validate X-Twilio-Signature

    form_data = await request.form()
    from_number = str(form_data.get("From", "")).strip()
    to_number = str(form_data.get("To", "")).strip()
    call_sid = str(form_data.get("CallSid", "")).strip()

    logger.info(
        f"[INCOMING_CALL] CallSid={call_sid} From={from_number} To={to_number}"
    )

    senior = get_senior_by_twilio_number(to_number)
    if not senior:
        logger.warning(
            f"[CALL_REJECTED] CallSid={call_sid} No senior profile found for {to_number}"
        )
        twiml = VoiceResponse()
        twiml.say("Sorry, this number is not configured in TROT.")
        twiml.hangup()
        return Response(content=str(twiml), media_type="application/xml")

    senior_id = senior["id"]
    guardian_id = senior.get("guardian_id")
    senior_real_phone = senior.get("phone")

    if not senior_real_phone:
        logger.error(
            f"[CALL_ERROR] CallSid={call_sid} Senior {senior_id} has no real phone set"
        )
        twiml = VoiceResponse()
        twiml.say("Senior contact phone is not configured.")
        twiml.hangup()
        return Response(content=str(twiml), media_type="application/xml")

    # Upsert caller reputation & record incoming call
    if guardian_id:
        upsert_caller_number(
            senior_id=senior_id,
            guardian_id=guardian_id,
            from_number=from_number,
        )
        insert_call(
            call_sid=call_sid,
            senior_id=senior_id,
            guardian_id=guardian_id,
            from_number=from_number,
        )

    # Initialize in-memory state
    call_states[call_sid] = {
        "status": "ringing",
        "senior_id": senior_id,
        "guardian_id": guardian_id,
        "from_number": from_number,
    }

    logger.info(
        f"[CALL_STARTED] CallSid={call_sid} From={from_number} To={to_number} -> Dialing {senior_real_phone}"
    )

    base_url = get_public_base_url(request)
    ws_url = get_public_ws_url(request)
    dial_complete_url = f"{base_url}/voice/dial-complete"
    dial_status_url = f"{base_url}/voice/dial-status"

    twiml = VoiceResponse()

    # 1. Asynchronous media stream of caller's audio (inbound track)
    start = Start()
    start.stream(url=ws_url)
    twiml.append(start)

    # 2. Dial senior's phone with timeout and callbacks (leave callerId out)
    dial = Dial(timeout=15, action=dial_complete_url)
    dial.number(
        senior_real_phone,
        status_callback=dial_status_url,
        status_callback_event="answered completed",
    )
    twiml.append(dial)
    twiml.hangup()

    return Response(content=str(twiml), media_type="application/xml")


@app.websocket("/ws/audio")
async def audio_websocket_endpoint(websocket: WebSocket):
    """
    Twilio Media Stream WebSocket handler.
    Receives connected, start, media, and stop events.
    Decodes mulaw audio packets and forwards live stream to Deepgram Nova-2.
    """
    await websocket.accept()
    logger.info("[WS_CONNECTED] WebSocket connection established")

    call_sid: Optional[str] = None
    stream_sid: Optional[str] = None
    dg_session = None
    chunk_count = 0
    total_bytes = 0

    try:
        from backend.services.transcribe import DeepgramLiveSession

        while True:
            message_text = await websocket.receive_text()
            data = json.loads(message_text)
            event = data.get("event")

            if event == "connected":
                logger.info("[WS_CONNECTED] Twilio protocol connected")

            elif event == "start":
                stream_sid = data.get("streamSid")
                start_info = data.get("start", {})
                call_sid = start_info.get("callSid")
                logger.info(
                    f"[WS_START] CallSid={call_sid} StreamSid={stream_sid}"
                )

                senior_id = None
                guardian_id = None
                if call_sid:
                    if call_sid in call_states:
                        call_states[call_sid]["stream_sid"] = stream_sid
                        senior_id = call_states[call_sid].get("senior_id")
                        guardian_id = call_states[call_sid].get("guardian_id")

                    if not senior_id or not guardian_id:
                        call_rec = get_call_by_sid(call_sid)
                        if call_rec:
                            senior_id = call_rec.get("senior_id")
                            guardian_id = call_rec.get("guardian_id")

                    from backend.services.detector import (
                        start_detector,
                        stop_detector,
                        ingest_transcript,
                    )

                    from_number = ""
                    if call_sid in call_states:
                        from_number = call_states[call_sid].get("from_number") or ""
                    if not from_number:
                        call_rec = get_call_by_sid(call_sid)
                        if call_rec:
                            from_number = call_rec.get("from_number") or ""

                    # Initialize detector with rolling buffer and heartbeat
                    if senior_id and guardian_id:
                        start_detector(
                            call_sid=call_sid,
                            senior_id=senior_id,
                            guardian_id=guardian_id,
                            from_number=from_number,
                        )

                    # Initialize and start Deepgram live streaming session
                    dg_session = DeepgramLiveSession(
                        call_sid=call_sid,
                        senior_id=senior_id,
                        guardian_id=guardian_id,
                        on_transcript=ingest_transcript,
                    )
                    await dg_session.start()

            elif event == "media":
                media_info = data.get("media", {})
                payload_b64 = media_info.get("payload", "")
                if payload_b64:
                    raw_audio = base64.b64decode(payload_b64)
                    chunk_count += 1
                    total_bytes += len(raw_audio)

                    # Forward audio bytes to Deepgram Nova-2
                    if dg_session and dg_session.is_active:
                        await dg_session.send_audio(raw_audio)

                    # Log progress periodically (every 50 chunks ~ 1s of audio)
                    if chunk_count % 50 == 0:
                        logger.info(
                            f"[WS_MEDIA] CallSid={call_sid} Chunks={chunk_count} TotalBytes={total_bytes}"
                        )

            elif event == "stop":
                logger.info(
                    f"[WS_STOP] CallSid={call_sid} StreamSid={stream_sid} TotalChunks={chunk_count} TotalBytes={total_bytes}"
                )
                if dg_session:
                    await dg_session.stop()
                    dg_session = None
                if call_sid:
                    from backend.services.detector import stop_detector
                    await stop_detector(call_sid)
                break

    except WebSocketDisconnect:
        logger.info(
            f"[WS_DISCONNECTED] CallSid={call_sid} WebSocket disconnected cleanly (TotalChunks={chunk_count})"
        )
    except Exception as e:
        logger.error(f"[WS_ERROR] CallSid={call_sid} Error in WebSocket loop: {e}", exc_info=True)
    finally:
        if dg_session:
            await dg_session.stop()
        if call_sid:
            try:
                from backend.services.detector import stop_detector
                await stop_detector(call_sid)
            except Exception:
                pass


@app.post("/voice/dial-status")
@app.post("/twilio/voice/dial-status")
async def handle_dial_status(request: Request):
    """
    Twilio status callback for the dialed child leg.
    When answered/in-progress, marks the parent call as in_progress.
    """
    # TODO: validate X-Twilio-Signature

    form_data = await request.form()
    child_call_sid = str(form_data.get("CallSid", "")).strip()
    parent_call_sid = str(form_data.get("ParentCallSid", "")).strip()
    call_status = str(form_data.get("CallStatus", "")).lower().strip()

    logger.info(
        f"[DIAL_STATUS] ParentCallSid={parent_call_sid} ChildCallSid={child_call_sid} CallStatus={call_status}"
    )

    # When call connects, mark parent call as in_progress
    if parent_call_sid and call_status in ("in-progress", "answered"):
        set_active_call_status(parent_call_sid, "in_progress")
        logger.info(
            f"[CALL_ANSWERED] ParentCallSid={parent_call_sid} -> Status set to in_progress"
        )
    elif parent_call_sid and call_status in ("no-answer", "busy", "failed", "canceled"):
        normalized = "no_answer" if call_status in ("no-answer", "canceled") else call_status
        set_active_call_status(parent_call_sid, normalized)
        try:
            complete_call(parent_call_sid, normalized)
            logger.info(
                f"[CALL_ENDED_FROM_STATUS] ParentCallSid={parent_call_sid} -> Status set to {normalized}"
            )
        except Exception as e:
            logger.warning(f"Failed to complete call {parent_call_sid} in dial-status: {e}")

    return Response(content="<Response/>", media_type="application/xml")


@app.post("/voice/dial-complete")
@app.post("/twilio/voice/dial-complete")
async def handle_dial_complete(request: Request):
    """
    Twilio action callback when <Dial> ends.
    Normalizes final status and completes the call record.
    """
    # TODO: validate X-Twilio-Signature

    form_data = await request.form()
    call_sid = str(form_data.get("CallSid", "")).strip()
    dial_status = str(form_data.get("DialCallStatus", "")).lower().strip()

    status_map = {
        "no-answer": "no_answer",
        "canceled": "no_answer",
        "completed": "completed",
        "answered": "completed",
        "busy": "busy",
        "failed": "failed",
    }
    normalized_status = status_map.get(dial_status, "completed")

    logger.info(
        f"[DIAL_COMPLETE] CallSid={call_sid} DialCallStatus={dial_status} Normalized={normalized_status}"
    )

    if call_sid:
        prev_status = call_states.get(call_sid, {}).get("status")
        if call_sid in call_states:
            call_states[call_sid]["status"] = normalized_status
        try:
            complete_call(call_sid, normalized_status)
        except Exception as e:
            logger.warning(f"Failed to complete call {call_sid} in DB: {e}")

        # Post-call summary: generate if call had active conversation
        if prev_status == "in_progress" or normalized_status == "completed":
            try:
                from backend.services.classifier import generate_call_summary
                from backend.db import get_supabase_client, update_call_summary

                client = get_supabase_client()
                t_res = (
                    client.table("call_transcripts")
                    .select("text")
                    .eq("call_sid", call_sid)
                    .order("created_at")
                    .execute()
                )
                if t_res.data and len(t_res.data) > 0:
                    full_text = " ".join(row["text"] for row in t_res.data)
                    summary = generate_call_summary(full_text)
                    update_call_summary(call_sid, summary)
                    logger.info(f"[CALL_SUMMARY] CallSid={call_sid}: {summary}")
            except Exception as e:
                logger.warning(f"Failed to generate summary for {call_sid}: {e}")

    twiml = VoiceResponse()
    twiml.hangup()
    return Response(content=str(twiml), media_type="application/xml")
