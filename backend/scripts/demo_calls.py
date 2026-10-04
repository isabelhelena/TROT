"""Replay/reset simulated dashboard calls. Never places a Twilio call."""

import argparse
from datetime import datetime, timezone
import math
import os
import time
import uuid

DEMO_PREFIX = "DEMO_"
DEMO_CALLER = "+15555550199"
LINES = (
    "Hello, I'm calling from your bank's security department.",
    "We noticed an unusual transaction and need to act quickly.",
    "Please do not discuss this with anyone else while we secure your account.",
    "Buy gift cards today and read the codes to me to protect your savings.",
)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def unfinished(client, senior_id):
    rows = (client.table("calls").select("id,call_sid")
            .eq("senior_id", senior_id).in_("status", ["ringing", "in_progress"])
            .like("call_sid", r"DEMO\_%").execute().data)
    return [row for row in rows if row["call_sid"].startswith(DEMO_PREFIX)]


def reset(client, senior_id, dry_run=False):
    rows = unfinished(client, senior_id)
    if not dry_run:
        for row in rows:
            (client.table("calls").update({"status": "completed", "ended_at": timestamp()})
             .eq("id", row["id"]).eq("senior_id", senior_id)
             .like("call_sid", r"DEMO\_%").in_("status", ["ringing", "in_progress"]).execute())
    print(f"{'Would finish' if dry_run else 'Finished'} {len(rows)} unfinished simulated calls.")
    return len(rows)


def replay(client, senior_id, interval=3, warning_hold=15, sleep=time.sleep):
    profiles = client.table("profiles").select("id,role,guardian_id").eq("id", senior_id).limit(1).execute().data
    if not profiles or profiles[0]["role"] != "senior" or not profiles[0].get("guardian_id"):
        raise ValueError("DEMO_SENIOR_ID must identify a pre-linked senior profile.")
    if unfinished(client, senior_id):
        raise ValueError("An unfinished simulated call exists. Run the reset command first.")
    guardian_id = profiles[0]["guardian_id"]
    sid = DEMO_PREFIX + uuid.uuid4().hex
    common = {"call_sid": sid, "senior_id": senior_id, "guardian_id": guardian_id}
    client.table("calls").insert({**common, "from_number": DEMO_CALLER, "status": "ringing", "risk": "none"}).execute()
    print(f"[DEMO_STARTED] {sid} — simulated data, no phone call placed")
    try:
        sleep(interval)
        client.table("calls").update({"status": "in_progress"}).eq("call_sid", sid).execute()
        for line in LINES:
            client.table("call_transcripts").insert({**common, "text": line}).execute()
            sleep(interval)
        client.table("alerts").insert({
            **common, "contact_number": DEMO_CALLER, "scam_type": "bank_impersonation",
            "confidence": 0.95, "severity": "high", "trigger": "keyword",
            "summary": "Simulated alert: caller requests gift cards and secrecy while impersonating a bank.",
        }).execute()
        client.table("calls").update({"risk": "scam"}).eq("call_sid", sid).execute()
        print(f"[DEMO_ALERT] {sid} — holding warning for {warning_hold:g} seconds")
        sleep(warning_hold)
    finally:
        client.table("calls").update({"status": "completed", "ended_at": timestamp()}).eq("call_sid", sid).execute()
        print(f"[DEMO_COMPLETED] {sid}")
    return sid


def nonnegative(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be a finite nonnegative number")
    return number


def main():
    # Load configuration only for this command; do not print credentials.
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["replay", "reset"])
    parser.add_argument("--senior-id", default=os.getenv("DEMO_SENIOR_ID"))
    parser.add_argument("--interval", type=nonnegative, default=3)
    parser.add_argument("--warning-hold", type=nonnegative, default=15)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run and args.command == "replay":
        print("SIMULATED replay plan: ringing → in_progress → 4 transcript rows → 1 alert → completed.")
        print("No database writes or phone calls performed.")
        return
    if not args.senior_id:
        parser.error("Set DEMO_SENIOR_ID or pass --senior-id with the senior profile UUID.")
    try:
        uuid.UUID(args.senior_id)
    except ValueError:
        parser.error("Senior ID must be a UUID.")
    from backend.db import get_supabase_client
    client = get_supabase_client()
    try:
        if args.command == "reset":
            reset(client, args.senior_id, args.dry_run)
        else:
            replay(client, args.senior_id, args.interval, args.warning_hold)
    except KeyboardInterrupt:
        print("Replay interrupted. Use reset if an unfinished simulated call remains.")
    except Exception:
        # SDK exceptions can include request details; avoid exposing service credentials.
        parser.exit(1, "Demo command failed. Check configuration, schema, and connectivity; reset unfinished demo calls before retrying.\n")


if __name__ == "__main__":
    main()
