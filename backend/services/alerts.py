import os
import logging
from typing import Optional, Dict, Any
from dotenv import load_dotenv
from twilio.rest import Client as TwilioClient

from backend.db import (
    insert_alert,
    update_alert,
    update_call_risk,
    increment_number_threat,
)

load_dotenv()
logger = logging.getLogger("trot.alerts")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()


def get_twilio_client() -> Optional[TwilioClient]:
    """Returns Twilio REST client if credentials are configured."""
    if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    return None


def record_scam_alert(
    call_sid: str,
    senior_id: str,
    guardian_id: str,
    contact_number: str,
    scam_type: str,
    severity: str,
    confidence: float,
    trigger: str,
    summary: str,
) -> bool:
    """
    Persists an alert, updates call risk status, and increments caller threat count.
    Enforces exactly one alert per call via DB unique constraint.
    Returns True if a new alert was created, False if deduplicated.
    """
    logger.info(
        f"[ALERT_TRIGGERED] CallSid={call_sid} ScamType={scam_type} "
        f"Severity={severity} Confidence={confidence:.2f} Trigger={trigger}"
    )

    alert_row = insert_alert(
        call_sid=call_sid,
        senior_id=senior_id,
        guardian_id=guardian_id,
        contact_number=contact_number,
        scam_type=scam_type,
        severity=severity,
        confidence=confidence,
        trigger=trigger,
        summary=summary,
    )

    if not alert_row:
        logger.info(
            f"[ALERT_DEDUPED] CallSid={call_sid} Alert already recorded for this call"
        )
        return False

    # Mark call risk as scam (or suspicious if low severity)
    risk_level = "scam" if severity == "high" else "suspicious"
    update_call_risk(call_sid, risk_level)

    # Increment reputation threat count for this caller
    increment_number_threat(senior_id, contact_number)

    logger.info(
        f"[ALERT_WRITTEN] CallSid={call_sid} AlertId={alert_row.get('id')} "
        f"Risk={risk_level} Summary=\"{summary}\""
    )

    # Dispatch Guardian Notification (Twilio Voice Buzz Call)
    try:
        from backend.db import get_profile_by_id
        from backend.services.notify import send_guardian_voice_buzz

        guardian_profile = get_profile_by_id(guardian_id) if guardian_id else None
        senior_profile = get_profile_by_id(senior_id) if senior_id else None

        guardian_phone = guardian_profile.get("phone") if guardian_profile else None
        senior_name = (
            (senior_profile.get("name") if senior_profile else None)
            or "Your Senior"
        )

        if guardian_phone:
            send_guardian_voice_buzz(
                guardian_phone=guardian_phone,
                senior_name=senior_name,
                scam_type=scam_type,
            )
        else:
            logger.info(
                f"[NOTIFY_SKIPPED] No phone configured for guardian_id={guardian_id}"
            )
    except Exception as e:
        logger.warning(
            f"[NOTIFY_ERROR] Failed to dispatch guardian voice buzz for {call_sid}: {e}"
        )

    return True


def update_scam_alert(
    call_sid: str,
    scam_type: str,
    severity: str,
    confidence: float,
    summary: str,
) -> bool:
    """
    Updates an existing scam alert with escalated confidence, summary, and severity.
    Ratchets call risk upward if severity is high.
    """
    logger.info(
        f"[ALERT_RE_EVALUATED] CallSid={call_sid} ScamType={scam_type} "
        f"Severity={severity} Confidence={confidence:.2f}"
    )
    if severity == "high":
        update_call_risk(call_sid, "scam")

    updated = update_alert(
        call_sid=call_sid,
        confidence=confidence,
        summary=summary,
        severity=severity,
        scam_type=scam_type,
    )
    return bool(updated)


def end_active_call(
    call_sid: str,
    reason: str = "Scam detected",
    spoken_warning: Optional[str] = None,
    child_call_sid: Optional[str] = None,
) -> bool:
    """
    Immediately terminates an ongoing call via the Twilio REST API.
    If child_call_sid (senior's handset leg) is provided and spoken_warning exists,
    updates the senior's leg to play a calm safety message before disconnecting.
    """
    client = get_twilio_client()
    if not client:
        logger.warning(
            f"[END_CALL_SKIPPED] Twilio credentials not configured for {call_sid}"
        )
        return False

    try:
        # 1. Play spoken warning to the senior on their child leg
        if child_call_sid and spoken_warning:
            try:
                twiml_warning = (
                    f'<Response>'
                    f'<Say voice="Polly.Joanna-Neural">'
                    f'TROT security alert. {spoken_warning}'
                    f'</Say>'
                    f'<Hangup/>'
                    f'</Response>'
                )
                client.calls(child_call_sid).update(twiml=twiml_warning)
                logger.info(
                    f"[WARN_SENIOR_PLAYED] Spoke warning on ChildCallSid={child_call_sid}: \"{spoken_warning}\""
                )
            except Exception as e:
                logger.warning(
                    f"[WARN_SENIOR_FAILED] Could not update child leg {child_call_sid}: {e}"
                )

        # 2. Terminate the scammer's parent call leg
        client.calls(call_sid).update(status="completed")
        logger.info(
            f"[CALL_TERMINATED_BY_AGENT] CallSid={call_sid} Successfully disconnected. Reason: {reason}"
        )
        return True
    except Exception as e:
        logger.error(
            f"[END_CALL_FAILED] CallSid={call_sid} Failed to terminate: {e}"
        )
        return False


def play_warning_to_senior(call_sid: str, message: str) -> bool:
    """
    Logs and prepares spoken warning for the senior.
    """
    logger.info(
        f"[WARN_SENIOR_EXECUTED] CallSid={call_sid} Spoken warning: \"{message}\""
    )
    return True
