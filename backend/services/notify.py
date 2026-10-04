import os
import logging
from typing import Optional
from dotenv import load_dotenv
from twilio.rest import Client as TwilioClient

load_dotenv()
logger = logging.getLogger("trot.notify")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "").strip()
TWILIO_WHATSAPP_FROM = os.getenv(
    "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"
).strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:3000").strip()


def get_twilio_client() -> Optional[TwilioClient]:
    """Returns Twilio REST client if credentials are configured."""
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    return None


def send_guardian_whatsapp_alert(
    guardian_phone: str,
    senior_name: str,
    contact_number: str,
    scam_type: str,
    confidence: float,
    summary: str,
) -> bool:
    """
    Sends an immediate rich security alert via Twilio WhatsApp Sandbox.
    Bypasses US cellular carrier A2P 10DLC SMS registration and spam filters.
    """
    client = get_twilio_client()
    if not client:
        logger.warning(
            f"[NOTIFY_SKIPPED] Twilio credentials missing for WhatsApp alert to {guardian_phone}"
        )
        return False

    if not guardian_phone:
        logger.warning("[NOTIFY_SKIPPED] Guardian phone number is empty.")
        return False

    clean_scam_type = scam_type.replace("_", " ").title()
    pct_confidence = int(round(confidence * 100))
    to_whatsapp = f"whatsapp:{guardian_phone}" if not guardian_phone.startswith("whatsapp:") else guardian_phone

    body = (
        f"🚨 *TROT SECURITY ALERT*\n\n"
        f"A live scam attempt was intercepted on *{senior_name}*'s phone:\n\n"
        f"• *Caller:* {contact_number}\n"
        f"• *Scam Type:* {clean_scam_type}\n"
        f"• *Confidence:* {pct_confidence}%\n"
        f"• *Details:* {summary}\n\n"
        f"🛡️ *Action:* TROT played a safety warning to {senior_name} and terminated the call.\n"
        f"📱 *Dashboard:* {PUBLIC_BASE_URL}/guardian"
    )

    try:
        msg = client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=to_whatsapp,
            body=body,
        )
        logger.info(
            f"[WHATSAPP_ALERT_SENT] MessageSid={msg.sid} To={to_whatsapp} "
            f"Senior={senior_name} ScamType={scam_type} Status={msg.status}"
        )
        return True
    except Exception as e:
        logger.error(
            f"[WHATSAPP_ALERT_FAILED] Failed to send WhatsApp alert to {to_whatsapp}: {e}"
        )
        return False


def send_guardian_voice_buzz(
    guardian_phone: str,
    senior_name: str,
    scam_type: str,
) -> bool:
    """
    Optional fallback: Places an automated 5-second voice buzz call to the guardian.
    Voice calls are completely exempt from A2P 10DLC regulations.
    """
    client = get_twilio_client()
    if not client or not TWILIO_PHONE_NUMBER or not guardian_phone:
        return False

    clean_scam_type = scam_type.replace("_", " ")
    twiml = (
        f'<Response>'
        f'<Say voice="Polly.Joanna-Neural">'
        f'Security alert from TROT. A potential {clean_scam_type} scam was detected '
        f'on {senior_name}\'s phone and disconnected for safety. '
        f'Please check your TROT guardian dashboard immediately.'
        f'</Say>'
        f'<Hangup/>'
        f'</Response>'
    )

    try:
        call = client.calls.create(
            to=guardian_phone,
            from_=TWILIO_PHONE_NUMBER,
            twiml=twiml,
        )
        logger.info(
            f"[VOICE_BUZZ_SENT] CallSid={call.sid} To={guardian_phone} Senior={senior_name}"
        )
        return True
    except Exception as e:
        logger.error(
            f"[VOICE_BUZZ_FAILED] Failed to place voice buzz to {guardian_phone}: {e}"
        )
        return False
