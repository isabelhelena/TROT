import logging
from fastapi import FastAPI, Request, Response
from twilio.twiml.voice_response import VoiceResponse, Dial

from backend.db import (
    get_senior_by_twilio_number,
    upsert_caller_number,
    insert_call,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("trot.voice")

app = FastAPI(title="TROT Backend", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok", "app": "TROT"}


@app.post("/voice")
async def handle_voice(request: Request):
    """
    Twilio voice webhook for incoming calls.
    Lookup senior by To number, log call record, and dial senior's real phone.
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

    logger.info(
        f"[CALL_STARTED] CallSid={call_sid} From={from_number} To={to_number} -> Dialing {senior_real_phone}"
    )

    # Return TwiML dialing senior's phone without callerId
    twiml = VoiceResponse()
    dial = Dial()
    dial.number(senior_real_phone)
    twiml.append(dial)

    return Response(content=str(twiml), media_type="application/xml")
