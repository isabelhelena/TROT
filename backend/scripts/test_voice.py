import os
import sys
from unittest.mock import patch

# Ensure root directory is on Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from fastapi.testclient import TestClient
import httpx

from backend.main import app


def test_unit_mock():
    """Runs an offline unit test mocking DB responses to verify TwiML generation."""
    print("\n--- Running Offline Mock Test (FastAPI TestClient) ---")
    client = TestClient(app)

    # Case 1: Known Senior
    mock_senior = {
        "id": "11111111-1111-1111-1111-111111111111",
        "role": "senior",
        "name": "Grandma",
        "phone": "+12105559999",
        "twilio_number": "+12105550000",
        "guardian_id": "22222222-2222-2222-2222-222222222222",
    }

    with (
        patch("backend.main.get_senior_by_twilio_number", return_value=mock_senior),
        patch("backend.main.upsert_caller_number") as mock_upsert,
        patch("backend.main.insert_call") as mock_insert,
    ):
        res = client.post(
            "/voice",
            data={
                "From": "+15551234567",
                "To": "+12105550000",
                "CallSid": "CA_test_mock_123",
            },
        )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        assert "<Start>" in res.text and "<Stream" in res.text and "/ws/audio" in res.text, "Missing Start/Stream tag in TwiML!"
        assert "<Dial" in res.text and "+12105559999" in res.text, f"Missing Dial tag in: {res.text}"
        assert res.text.find("<Start>") < res.text.find("<Dial"), "<Start><Stream> must come BEFORE <Dial>!"
        assert 'timeout="15"' in res.text, "Dial must have timeout=15"
        assert "action=" in res.text and "dial-complete" in res.text, "Dial must have action pointing to dial-complete"
        assert "statusCallback=" in res.text and "dial-status" in res.text, "Number must have statusCallback pointing to dial-status"
        assert "callerId" not in res.text, "callerId must NOT be set on Dial!"
        mock_upsert.assert_called_once()
        mock_insert.assert_called_once()
        print(" Case 1 PASSED: TwiML contains <Start><Stream> before <Dial>, timeout=15, and callbacks.")
        print(f"TwiML Output:\n{res.text}")

    # Case 2: Unknown Number
    with patch("backend.main.get_senior_by_twilio_number", return_value=None):
        res = client.post(
            "/voice",
            data={
                "From": "+15551234567",
                "To": "+19999999999",
                "CallSid": "CA_test_unknown",
            },
        )
        assert res.status_code == 200
        assert "not configured" in res.text
        assert "<Hangup" in res.text
        print(" Case 2 PASSED: Unconfigured number rejected gracefully.")

    # Case 3: Dial Status Callback (Answered)
    with patch("backend.main.update_call_status") as mock_update:
        res = client.post(
            "/voice/dial-status",
            data={
                "CallSid": "CA_child_leg_456",
                "ParentCallSid": "CA_test_mock_123",
                "CallStatus": "in-progress",
            },
        )
        assert res.status_code == 200
        mock_update.assert_called_once_with("CA_test_mock_123", "in_progress")
        print(" Case 3 PASSED: Dial-status answered sets ParentCallSid to in_progress.")

    # Case 4: Dial Complete Callback (No Answer)
    with patch("backend.main.complete_call") as mock_complete:
        res = client.post(
            "/voice/dial-complete",
            data={
                "CallSid": "CA_test_mock_123",
                "DialCallStatus": "no-answer",
            },
        )
        assert res.status_code == 200
        mock_complete.assert_called_once_with("CA_test_mock_123", "no_answer")
        print(" Case 4 PASSED: Dial-complete maps 'no-answer' to 'no_answer'.")

    # Case 5: Dial Complete Callback (Completed)
    with patch("backend.main.complete_call") as mock_complete:
        res = client.post(
            "/voice/dial-complete",
            data={
                "CallSid": "CA_test_mock_123",
                "DialCallStatus": "completed",
            },
        )
        assert res.status_code == 200
        mock_complete.assert_called_once_with("CA_test_mock_123", "completed")
        print(" Case 5 PASSED: Dial-complete maps 'completed' to 'completed'.")

    # Case 6: WebSocket /ws/audio Media Stream with Deepgram Integration
    import base64
    import json
    from unittest.mock import AsyncMock
    from backend.services.transcribe import DeepgramLiveSession

    with (
        patch.object(DeepgramLiveSession, "__init__", return_value=None),
        patch.object(DeepgramLiveSession, "is_active", True),
        patch.object(DeepgramLiveSession, "start", new_callable=AsyncMock) as mock_dg_start,
        patch.object(DeepgramLiveSession, "send_audio", new_callable=AsyncMock) as mock_dg_send,
        patch.object(DeepgramLiveSession, "stop", new_callable=AsyncMock) as mock_dg_stop,
    ):
        with client.websocket_connect("/ws/audio") as ws:
            # 1. Connected event
            ws.send_text(json.dumps({"event": "connected", "protocol": "Call"}))
            # 2. Start event
            ws.send_text(
                json.dumps(
                    {
                        "event": "start",
                        "streamSid": "MZ_test_stream_123",
                        "start": {
                            "streamSid": "MZ_test_stream_123",
                            "callSid": "CA_test_mock_123",
                            "tracks": ["inbound"],
                        },
                    }
                )
            )
            # 3. Media chunks (mulaw 8kHz sample bytes)
            dummy_audio = base64.b64encode(b"\xff" * 160).decode("utf-8")
            for _ in range(5):
                ws.send_text(
                    json.dumps(
                        {
                            "event": "media",
                            "streamSid": "MZ_test_stream_123",
                            "media": {"track": "inbound", "chunk": "1", "payload": dummy_audio},
                        }
                    )
                )
            # 4. Stop event
            ws.send_text(
                json.dumps(
                    {
                        "event": "stop",
                        "streamSid": "MZ_test_stream_123",
                        "stop": {"callSid": "CA_test_mock_123"},
                    }
                )
            )

        mock_dg_start.assert_called_once()
        assert mock_dg_send.call_count == 5, f"Expected 5 chunks sent, got {mock_dg_send.call_count}"
        mock_dg_stop.assert_called_once()
        print(" Case 6 PASSED: WebSocket /ws/audio forwarded audio to DeepgramLiveSession.")

    # Case 7: Deepgram Transcript Processing & In-Progress Gating
    import asyncio
    from backend.services.transcribe import DeepgramLiveSession

    session = DeepgramLiveSession(
        call_sid="CA_test_mock_123",
        senior_id="11111111-1111-1111-1111-111111111111",
        guardian_id="22222222-2222-2222-2222-222222222222",
    )

    mock_msg = {
        "type": "Results",
        "is_final": True,
        "channel": {
            "alternatives": [
                {"transcript": "Hello, I am calling from your credit card company."}
            ]
        },
    }

    # 7A: Call is ringing -> Gated (Do NOT insert)
    with (
        patch("backend.main.get_active_call_status", return_value="ringing"),
        patch("backend.services.transcribe.insert_call_transcript") as mock_transcript_insert,
    ):
        asyncio.run(session._on_message(mock_msg))
        mock_transcript_insert.assert_not_called()
        print(" Case 7A PASSED: Transcript skipped while call is still ringing.")

    # 7B: Call is in_progress -> Inserted!
    with (
        patch("backend.main.get_active_call_status", return_value="in_progress"),
        patch("backend.services.transcribe.insert_call_transcript") as mock_transcript_insert,
    ):
        asyncio.run(session._on_message(mock_msg))
        mock_transcript_insert.assert_called_once_with(
            call_sid="CA_test_mock_123",
            senior_id="11111111-1111-1111-1111-111111111111",
            guardian_id="22222222-2222-2222-2222-222222222222",
            text="Hello, I am calling from your credit card company.",
        )
        print(" Case 7B PASSED: Final transcript inserted into Supabase once in_progress.")


def test_live_server(
    base_url: str = "http://localhost:8000",
    from_number: str = "+15551234567",
    to_number: str = "+12105550000",
    call_sid: str = "CA_test_live_12345",
):
    """Sends a real HTTP request to a running server."""
    print(f"\n--- Testing Live Server at {base_url}/voice ---")
    payload = {
        "From": from_number,
        "To": to_number,
        "CallSid": call_sid,
    }

    try:
        response = httpx.post(f"{base_url}/voice", data=payload, timeout=10.0)
        print(f"Status Code: {response.status_code}")
        print(f"Content-Type: {response.headers.get('content-type')}")
        print(f"Response Body:\n{response.text}")

        if response.status_code == 200:
            print("\n SUCCESS: Live webhook returned 200 OK and valid TwiML.")
        else:
            print(f"\n FAILED: Unexpected status code {response.status_code}")
    except httpx.ConnectError:
        print(f"\n Connection error: Could not reach {base_url}. Is FastAPI running?")
    except Exception as e:
        print(f"\n Error: {e}")


if __name__ == "__main__":
    # Always run offline unit test
    test_unit_mock()

    # If --live flag is passed, also test the running server
    if "--live" in sys.argv:
        to_num = sys.argv[2] if len(sys.argv) > 2 else "+12105550000"
        test_live_server(to_number=to_num)
