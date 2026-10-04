import os
import logging
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, Response
from twilio.twiml.voice_response import VoiceResponse, Dial

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
    Lookup senior by To number, log call record, and dial senior's real phone
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
    }

    logger.info(
        f"[CALL_STARTED] CallSid={call_sid} From={from_number} To={to_number} -> Dialing {senior_real_phone}"
    )

    # Build TwiML with dial timeout and callbacks
    base_url = get_public_base_url(request)
    dial_complete_url = f"{base_url}/voice/dial-complete"
    dial_status_url = f"{base_url}/voice/dial-status"

    twiml = VoiceResponse()
    dial = Dial(timeout=15, action=dial_complete_url)
    dial.number(
        senior_real_phone,
        status_callback=dial_status_url,
        status_callback_event="answered completed",
    )
    twiml.append(dial)

    return Response(content=str(twiml), media_type="application/xml")


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
        if call_sid in call_states:
            call_states[call_sid]["status"] = normalized_status
        try:
            complete_call(call_sid, normalized_status)
        except Exception as e:
            logger.warning(f"Failed to complete call {call_sid} in DB: {e}")

    return Response(content="<Response/>", media_type="application/xml")
