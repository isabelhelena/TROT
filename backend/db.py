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
