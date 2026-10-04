"""Minimal TROT incoming-call bridge."""

import logging
import os
import re

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse

logger = logging.getLogger("uvicorn.error")


app = FastAPI(title="TROT Voice Bridge")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/twilio/voice")
async def incoming_voice():
    logger.info("Incoming Twilio voice webhook received at /twilio/voice")
    numbers = {}
    errors = []
    for name in ("PROTECTED_PHONE_NUMBER", "TWILIO_PHONE_NUMBER"):
        number = os.environ.get(name, "").strip()
        if not number:
            errors.append(f"{name} is missing.")
        elif not re.fullmatch(r"\+[1-9][0-9]{1,14}", number):
            errors.append(f"{name} must be in E.164 format (+ followed by 2–15 digits).")
        numbers[name] = number
    if errors:
        raise HTTPException(status_code=503, detail=" ".join(errors))

    twiml = VoiceResponse()
    twiml.say("This call is protected by TROT.")
    dial = twiml.dial(caller_id=numbers["TWILIO_PHONE_NUMBER"], answer_on_bridge=True)
    dial.number(numbers["PROTECTED_PHONE_NUMBER"])
    return Response(content=str(twiml), media_type="application/xml")
