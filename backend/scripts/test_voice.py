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
        assert "<Dial>" in res.text and "+12105559999" in res.text, f"Missing Dial tag in: {res.text}"
        assert "callerId" not in res.text, "callerId must NOT be set on Dial!"
        mock_upsert.assert_called_once()
        mock_insert.assert_called_once()
        print(" Case 1 PASSED: Known senior dialed correctly without callerId.")
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
