# TROT
RowdyHacks 2026

Threat Reduction and Oversight Technology: first Twilio voice-call milestone.
The FastAPI backend bridges incoming calls to a configured protected phone.
There is no recording, Media Streams, transcription, AI analysis, storage, or frontend yet.

## Local setup

Run these commands from the repository root (Python 3.10+):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
cp .env.example .env
```

Edit `.env` and replace the placeholder `PROTECTED_PHONE_NUMBER` with the
protected person's real, Twilio-verified number in E.164 format (`+` followed
by country code and number, without spaces). Set `TWILIO_PHONE_NUMBER` to your
purchased Twilio voice number in the same format; it is the outbound caller ID.
No Twilio Account SID or Auth Token is needed
to generate TwiML. `.env` is ignored by git.

Start the server from the repository root:

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload --env-file .env
```

The voice endpoint returns HTTP 503 with the affected environment variable names
if either phone number is missing or malformed. `/health` remains available.
After editing `.env`, stop and restart the server with the command above;
automatic code reload does not reload the environment file.
In a second terminal, with ngrok installed and authenticated:

```bash
ngrok http 8000
```

## Twilio configuration and complete call test

1. Have two distinct real phones available: phone A is the caller, and phone B
   belongs to the protected person. Verify both numbers in your Twilio trial
   account under **Phone Numbers → Manage → Verified Caller IDs** (or the
   trial setup's verified recipients screen). Set phone B as
   `PROTECTED_PHONE_NUMBER`; neither A nor B is your Twilio number.
2. In **Phone Numbers → Manage → Active Numbers**, open your voice-enabled
   Twilio trial number. Under **Voice Configuration → A call comes in**, select
   **Webhook**, enter `https://<ngrok-domain>/twilio/voice`, select **HTTP POST**,
   and save. Use the HTTPS forwarding domain shown by ngrok, with no angle
   brackets. Update this setting whenever your ngrok domain changes.
3. Keep the server and ngrok running. From verified phone A, call your Twilio
   trial number. Follow any Twilio trial announcement instructions. Check the
   backend console for `Incoming Twilio voice webhook received at /twilio/voice`.
4. Phone B should ring. Leave it ringing briefly: caller A should continue
   hearing ringing. Answer B and confirm that both people can hear each other.
   Hang up to finish. Voicemail also counts as an answer, so answer B yourself
   before voicemail picks up for this test.
5. If the call fails, inspect the ngrok request inspector at
   `http://127.0.0.1:4040` and Twilio's call logs/debugger. Confirm the webhook
   returned HTTP 200 XML, both real numbers are verified, and the configured
   destination matches phone B. Trial announcements are controlled by Twilio.

The app says "This call is protected by TROT." before
`<Dial callerId="…" answerOnBridge="true">`. This announcement answers the
incoming call before dialing; callers then hear ringing while the destination
rings. The outbound caller ID is your configured Twilio number.
The helper SDK generates the XML and the response uses `application/xml`.
This prototype endpoint does not yet validate Twilio webhook signatures.

Official references: [Dial and answerOnBridge](https://www.twilio.com/docs/voice/twiml/dial),
[Twilio Voice trial setup](https://www.twilio.com/docs/usage/trials/try-out-voice).

## Local checks

With the server running:

```bash
curl -i http://127.0.0.1:8000/health
curl -i -X POST http://127.0.0.1:8000/twilio/voice
python -m compileall -q backend
```

Expect `{"status":"ok"}` from health and an XML response containing
`<Say>This call is protected by TROT.</Say>` followed by
`<Dial callerId="…" answerOnBridge="true"><Number>…</Number></Dial>` from the webhook.
The local POST only checks TwiML generation; it does not place a phone call.
