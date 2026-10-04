# Phase 1 Step-by-Step Breakdown & Review Plan

> **Goal:** Break down the riskiest phase (**Call Lifecycle + Audio to Live Transcript**) into 3 smaller, self-contained sub-phases with clear verification checkpoints and commit boundaries.

---

## Why Break Phase 1 Down?
Telephony audio streaming has two distinct layers:
1. **The Telephony State Machine:** Handling Twilio webhooks, timeouts, and state transitions in Supabase (`ringing` $\rightarrow$ `in_progress` $\rightarrow$ `completed` / `no_answer`).
2. **The Audio Pipeline:** WebSocket connection $\rightarrow$ raw mulaw byte decoding $\rightarrow$ Deepgram Nova-2 streaming $\rightarrow$ database inserts.

Mixing both at once makes debugging difficult if something fails. By decoupling them, we guarantee call lifecycle works before streaming audio, and audio bytes work before calling Deepgram.

---

## Sub-Phase 1A: Call Lifecycle & Dial Callbacks
> **Focus:** Webhooks, Dial Timeout, Status Updates (No Audio / Deepgram yet)  
> **Target Commit:** `feat(voice): implement call lifecycle callbacks and dial timeout`

### 1. What Changes
- **TwiML Upgrade in `backend/main.py`:**
  Update `<Dial>` to include:
  ```xml
  <Dial timeout="15" action="https://HOST/voice/dial-complete">
    <Number statusCallback="https://HOST/voice/dial-status"
            statusCallbackEvent="answered completed">
      +1SENIOR_PHONE
    </Number>
  </Dial>
  ```
- **New Endpoints in `backend/main.py`:**
  - `POST /voice/dial-status`:
    - Receives Twilio child callback (`ParentCallSid`, `CallStatus`).
    - When `CallStatus` is `in-progress` (or answered): updates `calls.status = 'in_progress'`.
  - `POST /voice/dial-complete`:
    - Receives `DialCallStatus` (`completed`, `no-answer`, `busy`, `failed`).
    - Maps `no-answer` $\rightarrow$ `'no_answer'`, `completed` $\rightarrow$ `'completed'`, etc.
    - Updates `calls.status` and sets `ended_at = now()`.
    - Returns empty `<Response/>`.
- **Database Helper in `backend/db.py`:**
  - `update_call_status(call_sid: str, status: str)`
  - `complete_call(call_sid: str, status: str)`

### 2. Verification Checkpoint 1A
- **Test 1A.1 (No Answer):** Dial the Twilio number. Let it ring. After ~15 seconds, it stops ringing.
  - Verify in Supabase: `calls.status` becomes `'no_answer'`, `ended_at` is set.
- **Test 1A.2 (Answer & Hangup):** Dial the Twilio number. Answer on senior's phone.
  - Verify in Supabase: `calls.status` becomes `'in_progress'`.
  - Hang up.
  - Verify in Supabase: `calls.status` becomes `'completed'`, `ended_at` is set.

---

## Sub-Phase 1B: Twilio Audio Media Stream (`WS /ws/audio`)
> **Focus:** WebSocket Ingress, Twilio Media Stream, Audio Byte Decoding  
> **Target Commit:** `feat(audio): add twilio media stream websocket handler`

### 1. What Changes
- **TwiML Upgrade in `backend/main.py`:**
  Add `<Start><Stream>` before `<Dial>`:
  ```xml
  <Response>
    <Start>
      <Stream url="wss://HOST/ws/audio" />
    </Start>
    <Dial ...>...</Dial>
  </Response>
  ```
  *(Uses `PUBLIC_BASE_URL` from `.env` to build `wss://` URL)*.
- **WebSocket Endpoint in `backend/main.py` (or `backend/routes/audio_ws.py`):**
  - Accepts `WS /ws/audio`.
  - Twilio event loop:
    - `connected`: Log connection established.
    - `start`: Extract `callSid` and `streamSid`. Map connection to call.
    - `media`: Extract base64 `payload`, decode into raw mulaw bytes, count packets/bytes.
    - `stop`: Log stream closed.

### 2. Verification Checkpoint 1B
- Place a call and answer.
- Server terminal logs:
  ```
  [WS_CONNECTED] Twilio media stream connected
  [WS_START] CallSid=CA... StreamSid=MZ...
  [WS_MEDIA] Received 50 audio chunks (32,000 bytes)
  [WS_STOP] CallSid=CA... Stream stopped
  ```
- Confirms Twilio is successfully streaming caller audio to our WebSocket.

---

## Sub-Phase 1C: Deepgram Nova-2 Streaming STT & Database Writes
> **Focus:** Deepgram Live Client, Speech-to-Text, `call_transcripts` Inserts  
> **Target Commit:** `feat(stt): stream caller audio to deepgram nova-2 and save transcripts`

### 1. What Changes
- **Add Deepgram Dependency & API Key:**
  - Add `DEEPGRAM_API_KEY` to `.env`.
  - Add `deepgram-sdk` to `backend/requirements.txt`.
- **Deepgram Transcription Service (`backend/services/transcribe.py`):**
  - Manages a live WebSocket session with Deepgram:
    - `model: "nova-2"`
    - `encoding: "mulaw"`
    - `sample_rate: 8000`
    - `punctuate: true`
  - Event listener on Deepgram transcription:
    - Filters: ignore interim results, accept **only `is_final == true`**.
    - For each final utterance:
      - Log: `[TRANSCRIPT] <call_sid>: "Hello, this is Bank of America..."`
      - Insert row into Supabase `call_transcripts` table (`call_sid`, `senior_id`, `guardian_id`, `text`).
- **Connect `WS /ws/audio` to Deepgram:**
  - On `start`: start Deepgram live connection.
  - On `media`: pipe decoded mulaw audio bytes to Deepgram connection.
  - On `stop`: close Deepgram connection cleanly.

### 2. Verification Checkpoint 1C (Full Phase 1 Checkpoint)
- Call the Twilio number, answer on senior phone, and speak 2-3 sentences.
- Verify:
  - Terminal prints the transcript lines in real time.
  - Supabase `call_transcripts` table has each final sentence as an individual row.

---

## Summary of Sub-Phases & Checkpoints

| Sub-Phase | Scope | Risk / Complexity | How to Verify |
| :--- | :--- | :--- | :--- |
| **1A: Call Lifecycle** | `/voice/dial-status`, `/voice/dial-complete`, timeout="15", Supabase call status updates | Low | 15s no-answer test & answer-hangup test in Supabase |
| **1B: Audio Ingress** | `<Start><Stream>`, `WS /ws/audio`, base64 decode mulaw audio | Medium | Console logs showing `[WS_MEDIA]` chunk receipts |
| **1C: Deepgram STT** | Deepgram Nova-2 live client, `is_final` filtering, `call_transcripts` inserts | Medium | Speaking into phone produces real-time rows in `call_transcripts` |

---

## Review & Next Actions
Take a look at this breakdown. If this sequence looks good to you, we can start immediately with **Sub-Phase 1A**!
