import os
import logging
from typing import Optional, Dict, Any
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

logger = logging.getLogger("trot.db")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

_supabase_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """Returns a singleton Supabase client using the service role key."""
    global _supabase_client
    if _supabase_client is not None:
        return _supabase_client

    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be configured in .env"
        )

    _supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _supabase_client


def get_senior_by_twilio_number(to_number: str) -> Optional[Dict[str, Any]]:
    """Looks up senior profile by their assigned twilio_number."""
    client = get_supabase_client()
    res = (
        client.table("profiles")
        .select("*")
        .eq("twilio_number", to_number)
        .eq("role", "senior")
        .execute()
    )
    if res.data and len(res.data) > 0:
        return res.data[0]
    return None


def upsert_caller_number(senior_id: str, guardian_id: str, from_number: str) -> None:
    """Upserts caller into the numbers table for reputation tracking."""
    client = get_supabase_client()
    data = {
        "senior_id": senior_id,
        "guardian_id": guardian_id,
        "number": from_number,
        "status": "unknown",
    }
    try:
        client.table("numbers").upsert(data, on_conflict="senior_id,number").execute()
    except Exception as e:
        logger.warning(f"Failed to upsert caller number {from_number}: {e}")


def insert_call(
    call_sid: str, senior_id: str, guardian_id: str, from_number: str
) -> Dict[str, Any]:
    """Inserts a new call row with ringing status."""
    client = get_supabase_client()
    data = {
        "call_sid": call_sid,
        "senior_id": senior_id,
        "guardian_id": guardian_id,
        "from_number": from_number,
        "status": "ringing",
        "risk": "none",
    }
    res = client.table("calls").insert(data).execute()
    return res.data[0] if res.data else {}


def update_call_status(call_sid: str, status: str) -> Optional[Dict[str, Any]]:
    """Updates the status of an existing call (e.g. in_progress)."""
    client = get_supabase_client()
    res = (
        client.table("calls")
        .update({"status": status})
        .eq("call_sid", call_sid)
        .execute()
    )
    return res.data[0] if res.data else None


def complete_call(call_sid: str, status: str) -> Optional[Dict[str, Any]]:
    """Marks a call as finished with final status and ended_at timestamp."""
    from datetime import datetime, timezone

    client = get_supabase_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    res = (
        client.table("calls")
        .update({"status": status, "ended_at": now_iso})
        .eq("call_sid", call_sid)
        .execute()
    )
    return res.data[0] if res.data else None


def get_call_by_sid(call_sid: str) -> Optional[Dict[str, Any]]:
    """Fetches a call record by its Twilio call_sid."""
    client = get_supabase_client()
    res = client.table("calls").select("*").eq("call_sid", call_sid).execute()
    return res.data[0] if res.data else None


def insert_call_transcript(
    call_sid: str, senior_id: str, guardian_id: str, text: str
) -> Dict[str, Any]:
    """Inserts a confirmed final transcript utterance into call_transcripts."""
    client = get_supabase_client()
    data = {
        "call_sid": call_sid,
        "senior_id": senior_id,
        "guardian_id": guardian_id,
        "text": text,
    }
    res = client.table("call_transcripts").insert(data).execute()
    return res.data[0] if res.data else {}


def get_caller_number_record(
    senior_id: str, from_number: str
) -> Optional[Dict[str, Any]]:
    """Fetches the caller number record for a specific senior."""
    client = get_supabase_client()
    res = (
        client.table("numbers")
        .select("*")
        .eq("senior_id", senior_id)
        .eq("number", from_number)
        .execute()
    )
    return res.data[0] if res.data else None


def get_network_threat_count(from_number: str) -> int:
    """
    Computes shared network-wide reputation for a caller.
    Sums threat_count across all senior records for this phone number.
    """
    client = get_supabase_client()
    try:
        res = (
            client.table("numbers")
            .select("threat_count")
            .eq("number", from_number)
            .execute()
        )
        if res.data:
            return sum(int(row.get("threat_count") or 0) for row in res.data)
    except Exception as e:
        logger.warning(
            f"Failed to query network threat count for {from_number}: {e}"
        )
    return 0


def insert_alert(
    call_sid: str,
    senior_id: str,
    guardian_id: str,
    contact_number: str,
    scam_type: str,
    severity: str,
    confidence: float,
    trigger: str,
    summary: str,
) -> Optional[Dict[str, Any]]:
    """
    Inserts a fraud alert row. Enforces exactly one alert per call.
    Uses ON CONFLICT (call_sid) DO NOTHING to prevent duplicates.
    """
    client = get_supabase_client()
    data = {
        "call_sid": call_sid,
        "senior_id": senior_id,
        "guardian_id": guardian_id,
        "contact_number": contact_number,
        "scam_type": scam_type,
        "severity": severity,
        "confidence": round(float(confidence), 2),
        "trigger": trigger,
        "summary": summary,
        "acknowledged": False,
    }
    try:
        # Note: alerts_one_per_call unique constraint exists on call_sid
        res = client.table("alerts").upsert(data, on_conflict="call_sid", ignore_duplicates=True).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
    except Exception as e:
        logger.info(f"Alert already exists or insert skipped for {call_sid}: {e}")
    return None


def update_call_risk(call_sid: str, risk: str) -> Optional[Dict[str, Any]]:
    """Updates the risk level of a call ('none', 'suspicious', 'scam')."""
    client = get_supabase_client()
    try:
        res = (
            client.table("calls")
            .update({"risk": risk})
            .eq("call_sid", call_sid)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"Failed to update risk for call {call_sid}: {e}")
    return None


def increment_number_threat(senior_id: str, from_number: str) -> None:
    """Increments the threat count for a number and marks status as suspicious."""
    client = get_supabase_client()
    try:
        existing = get_caller_number_record(senior_id, from_number)
        current_count = int(existing.get("threat_count", 0)) if existing else 0
        new_count = current_count + 1

        client.table("numbers").update(
            {"threat_count": new_count, "status": "suspicious"}
        ).eq("senior_id", senior_id).eq("number", from_number).execute()
    except Exception as e:
        logger.warning(
            f"Failed to increment threat count for {from_number}: {e}"
        )


def update_call_summary(call_sid: str, summary: str) -> Optional[Dict[str, Any]]:
    """Persists plain-language Gemini summary to calls table."""
    client = get_supabase_client()
    try:
        res = (
            client.table("calls")
            .update({"summary": summary})
            .eq("call_sid", call_sid)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception as e:
        logger.warning(f"Failed to update summary for call {call_sid}: {e}")
    return None


