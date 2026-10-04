<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

# TROT: Threat Reduction and Oversight Technology

Hackathon project, ~24 hours. Protects seniors from phone scams in real time.
A guardian (family member) links to a senior. The senior uses a TROT (Twilio) phone
number. Calls to it ring the senior's real phone as normal, while TROT transcribes the
caller's audio, flags scams with an LLM, and alerts the guardian mid-call.

Voice only. SMS/text screening is explicitly OUT of scope (roadmap slide only).

## How to work in this repo

- **Build one phase at a time (see Phase Plan). Stop at each checkpoint and tell me how to verify it.** Do not start the next phase unprompted.
- Prefer the simplest thing that works. This is a hackathon: no ORM, no migrations, no premature abstraction.
- **Before writing code that touches Twilio, Deepgram, Gemini (`google-genai`), or Supabase Auth with Next.js (`@supabase/ssr`), check current docs** (Context7 MCP if available). SDK APIs change often; do not rely on memory.
- Never print, log, or commit secrets. Secrets live in `.env` (see Env Vars). `.env` is gitignored.
- If a requirement here conflicts with something you think is better, say so and ask. Don't silently deviate.
- Keep functions small and log key lifecycle events (call started, answered, keyword hit, LLM verdict, alert written) with the `call_sid`, because we will debug live.

## Stack

| Layer                | Tool                                                                               |
| -------------------- | ---------------------------------------------------------------------------------- |
| Telephony            | Twilio (voice webhooks, `<Dial>` bridging, Media Streams)                          |
| Backend              | Python, FastAPI, uvicorn, `twilio`, `supabase`, `google-genai`, Deepgram SDK       |
| STT                  | Deepgram Nova-2, streaming                                                         |
| LLM                  | Gemini Flash (model id from `GEMINI_MODEL` env var; verify the current id in docs) |
| DB / auth / realtime | Supabase (Postgres, Auth with Google + email fallback, Realtime, RLS)              |
| Frontend             | Next.js (App Router), Tailwind, `@supabase/supabase-js`, `@supabase/ssr`           |
| Hosting (dev)        | ngrok with a static domain pointing at FastAPI. Frontend runs on localhost.        |

## Roles

- **Guardian (trusted person):** dashboard with live calls, live transcript, alerts, suspicious numbers. Can acknowledge alerts, mark numbers trusted, and trigger an active call disconnect ("Hang up on Scammer").
- **Senior (vulnerable person):** calm, minimal screen. States: protected / active call / possible scam (with a `tel:` link to call the guardian).

## End-to-end flow

### Setup (one time)

1. Both users sign in (Google, or email fallback) and pick a role. The role picker inserts their `profiles` row.
2. Guardian dashboard calls a route handler that generates a single-use `pairing_code`.
3. Senior enters code + real phone number on ONE screen, then accepts a consent screen (sets `consented_at`).
4. `/api/pair` (service role) finds the guardian by code, sets `guardian_id` and `phone` on the senior's profile, and clears the code. Guardian dashboard goes live via Realtime on `profiles`.
5. `twilio_number` is assigned to the senior BY HAND (SQL update). Do not build number provisioning.

### Call (every call)

1. Caller dials the senior's Twilio number. Twilio POSTs (form-encoded) to `POST /voice`.
2. Backend looks up the senior by `To` == `profiles.twilio_number`, gets `guardian_id`, inserts a `calls` row (`status='ringing'`), upserts a `numbers` row for the caller.
3. Backend returns TwiML:
   ```xml
   <Response>
     <Start><Stream url="wss://HOST/ws/audio"/></Start>
     <Dial timeout="15" action="https://HOST/voice/dial-complete">
       <Number statusCallback="https://HOST/voice/dial-status"
               statusCallbackEvent="answered completed">+1SENIOR</Number>
     </Dial>
   </Response>
   ```
4. Senior's real phone rings and connects normally.
5. `POST /voice/dial-status`: on `answered`, set `calls.status='in_progress'` (child callback includes `ParentCallSid`, which maps to `calls.call_sid`).
6. `POST /voice/dial-complete`: read `DialCallStatus`, set `calls.status` to `completed` / `no_answer` / `busy` / `failed`, set `ended_at`, return an empty `<Response/>`.
7. `WS /ws/audio`: Twilio sends `connected`, `start`, `media` (base64 mulaw 8kHz), `stop`. The `start` event contains the call SID. Forward audio to Deepgram (`encoding=mulaw`, `sample_rate=8000`). On each `is_final` transcript, insert one row into `call_transcripts` and append to the in-memory buffer for that call.
8. Detection runs ONLY while the call is `in_progress` (see Detection). The stream opens at ring time, but analysis is skipped until the senior answers. This avoids analyzing carrier voicemail.
9. On a scam verdict: write the alert, mark `calls.risk`, bump `numbers.threat_count`, notify the guardian (Realtime dashboard + outbound Twilio voice call), and the senior screen flips to "possible scam" via Realtime.
10. At call end, Gemini writes a short plain-language `calls.summary`.

## Detection & Agentic Defense

- Per-call in-memory rolling buffer of final transcript text. Use the last ~60 seconds for the LLM.
- **Shared Network Reputation:** On call arrival, query network-wide reputation (`sum(threat_count)` across `numbers` for caller). If known threat, pass count into Gemini prompt context.
- **Keyword path:** word-boundary regex over new transcript text for red flags (gift card, warrant, wire transfer, bitcoin, arrest, social security, "don't tell anyone", IRS, etc.). On a hit, and once the buffer has at least ~15 words, call Gemini immediately.
- **Heartbeat path:** every ~20 seconds, call Gemini only if new transcript arrived since the last check.
- Keywords decide WHEN to ask Gemini. Gemini is the autonomous verdict & action maker.
- **Gemini Tool Calling:** Gemini evaluates threat and calls proportionate defense tools:
  - `notify_guardian(scam_type, severity, confidence, reason)`: writes alert row, updates call risk, buzzes guardian.
  - `warn_senior(message)`: plays spoken warning into the call leg.
  - `end_call(reason)`: immediately hangs up on the scammer via Twilio REST API.
  - `block_number(reason)`: marks number as `suspicious` for future calls.
- **One alert per call.** Insert with `on conflict (call_sid) do nothing` (unique index exists).
- Skip all analysis if the caller's `numbers.status == 'trusted'`.

## Hard rules (decisions already made, do not revisit without asking)

1. `<Start><Stream>` before `<Dial>`. NEVER `<Connect><Stream>` (it blocks `<Dial>`). Default inbound track only, so we transcribe the caller, not the senior.
2. Do NOT set `callerId` on `<Dial>`. Twilio then presents the original caller's number. We test on real phones early. Fallback if it shows the Twilio number: whisper screening (stretch).
3. `timeout="15"` on `<Dial>`, plus the `action` and `statusCallback` handlers above.
4. One `call_transcripts` insert per final utterance. No batching (the live transcript is the demo). On the client, append Realtime rows to state; do not refetch the table per event.
5. ALL pairing/linking and pairing-code generation go through Next.js route handlers using the service role key. `profiles` has no update policy by design, so a browser-client update will silently fail.
6. The service role key is server-side only (FastAPI and Next.js route handlers). Never expose it to the browser.
7. All phone numbers are E.164 (`+12105551234`) everywhere. Normalize at input; compare exactly to Twilio's `From`/`To`.
8. Backend uses the Supabase service role (bypasses RLS). Browser uses the anon key and relies on RLS. Guardians only ever see rows where `guardian_id = auth.uid()`, seniors where `senior_id = auth.uid()`.
9. Realtime is RLS-gated. If a dashboard receives no events, check the select policy and the `supabase_realtime` publication first.
10. Skip Twilio webhook signature validation for now (add a `# TODO: validate X-Twilio-Signature` marker). Production note, not a hackathon requirement.
11. Trial-account reality: only verified numbers can be called. Don't build around outbound SMS (carrier registration issues). The guardian "buzz" is an outbound Twilio VOICE call plus a browser notification.

## Schema

`schema.sql` in the repo root is the source of truth. Tables: `profiles`, `calls`, `call_transcripts`, `alerts`, `numbers`. Do not invent columns without updating `schema.sql` and telling me. The user runs SQL in the Supabase SQL editor.

## Repo layout

```
trot/
├── CLAUDE.md
├── schema.sql
├── .env.example
├── backend/
│   ├── main.py                  # FastAPI app, route registration
│   ├── db.py                    # supabase client (service role)
│   ├── routes/
│   │   ├── voice.py             # POST /voice, /voice/dial-status, /voice/dial-complete
│   │   └── audio_ws.py          # WS /ws/audio
│   ├── services/
│   │   ├── detector.py          # buffers, keyword path, heartbeat, debounce
│   │   ├── classifier.py        # Gemini prompt + JSON parsing
│   │   ├── transcribe.py        # Deepgram streaming connection
│   │   ├── alerts.py            # alert insert, numbers bump, guardian notify
│   │   └── notify.py            # outbound Twilio voice call to guardian
│   ├── scripts/
│   │   ├── simulate_webhooks.py # fake Twilio POSTs to /voice etc.
│   │   └── replay_transcript.py # feed a scripted transcript into the detector
│   ├── fixtures/                # scam + normal call transcripts
│   └── requirements.txt
└── web/                         # Next.js
    ├── app/
    │   ├── login/               # auth + role picker
    │   ├── guardian/            # dashboard
    │   ├── senior/              # pairing, consent, status screen
    │   └── api/pair/            # pairing + code generation route handlers
    └── lib/supabase/            # browser + server clients (@supabase/ssr)
```

## Env vars (names only; values in `.env`)

```
# backend
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_PHONE_NUMBER        # the TROT number (demo senior)
PUBLIC_BASE_URL            # ngrok static domain, https://...
DEEPGRAM_API_KEY
GEMINI_API_KEY
GEMINI_MODEL
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY

# web
NEXT_PUBLIC_SUPABASE_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY  # server-only (route handlers); never NEXT_PUBLIC_
```

## Test harnesses (build these early; most of the build should not need a real call)

- `scripts/simulate_webhooks.py`: POSTs realistic Twilio form data (`From`, `To`, `CallSid`, `ParentCallSid`, `CallStatus`, `DialCallStatus`) to `/voice`, `/voice/dial-status`, `/voice/dial-complete`. Verifies the call lifecycle and DB writes without placing a call.
- `scripts/replay_transcript.py`: feeds a fixture transcript into the detector line by line with realistic timing. Lets us tune the Gemini prompt and keyword trigger with no Twilio or Deepgram.
- Fixtures: 3-4 scam scripts (grandchild in jail, bank fraud, tech support/IRS) and 2-3 normal calls (family, doctor's office, a false-positive bait like "I got a warrant for my garden shed"). Expected result: exactly one alert on scams, zero on normal calls.
- Only the Phase 1 audio path needs live phone calls.

## Phase plan (build one at a time, stop at each checkpoint)

**Phase 0: Plumbing**
Run `schema.sql`; seed two auth users and profiles (SQL at the bottom of `schema.sql`); FastAPI `POST /voice` looks up the senior by `To`, inserts a `calls` row, returns TwiML that dials the senior. No `callerId`.
_Checkpoint:_ scammer phone calls the Twilio number, the senior phone rings and connects. Note what caller ID shows.

**Phase 1: Call lifecycle + audio to transcript**
Add `<Start><Stream>`, `/voice/dial-status`, `/voice/dial-complete`, `/ws/audio`, Deepgram streaming, `call_transcripts` inserts (final utterances only).
_Checkpoint:_ talking on the call produces transcript lines in the terminal and in Supabase; an unanswered call ends as `no_answer` after ~15s.

**Phase 2: Scam detection & Agentic Defense**
Detector (buffer, keyword path, heartbeat, `in_progress` gate, trusted-number skip, community network reputation query), Gemini classifier with function calling (`notify_guardian`, `warn_senior`, `end_call`, `block_number`), alert insert with `on conflict do nothing`, `calls.risk`, `numbers.threat_count`. Develop against `replay_transcript.py` first.
_Checkpoint:_ a scripted scam call triggers Gemini tool calls producing exactly one alert and action; a normal call produces none.

**Phase 3: Auth, pairing, dashboards** (can start in parallel with Phase 1; it only depends on the schema)
Supabase Auth (Google + email fallback), role picker, `/api/pair` and code generation route handlers, consent screen, guardian dashboard (live calls, live transcript, alert feed with acknowledge, suspicious numbers with mark-trusted, remote "Hang up on Scammer" button), senior status screen (protected / active call / possible scam with `tel:` link).
_Checkpoint (minimum viable demo):_ a scam call makes the guardian dashboard show the live transcript and an alert, senior screen flips to warning, and guardian can disconnect the call.

**Phase 4: Buzz + polish**
Outbound Twilio voice call to the guardian on alert (`notify.py`), browser notification backup, seed demo data, demo script, backup video. Feature freeze at the start of this phase.

**Stretch (only after the Phase 3 checkpoint):** spoken warning to the senior mid-call (Twilio call update with TTS or ElevenLabs), whisper screening (`<Number url=...>`), deployment (Vercel/Vultr).

## Cut list, in order

1. Spoken warning and whisper
2. Guardian buzz call (dashboard alert is enough)
3. Numbers ranking (hardcode rows)
4. Live pairing demo (pre-link accounts, show a recorded clip)

## Known gotchas

- Twilio webhooks are `application/x-www-form-urlencoded`, not JSON. Use FastAPI `Form(...)` or parse the form body.
- Twilio must reach FastAPI over public HTTPS/WSS (ngrok). `PUBLIC_BASE_URL` must be used to build the TwiML URLs, and the WebSocket URL uses `wss://`.
- Deepgram emits interim results; store only `is_final`.
- Supabase sessions share localStorage per browser profile. Test two logins with two browser profiles or an incognito window.
- Add `http://localhost:3000` to allowed redirects in both Google Cloud and Supabase; add demo accounts as test users on the Google consent screen.
- `<Dial>` to carrier voicemail still streams audio; the 15s timeout plus the `in_progress` gate prevent false positives.
- Browser testing only (no PWA). iOS home-screen PWAs have separate storage and flaky OAuth.

## Pitch notes (for README/demo)

- Gemini is used for scam classification (structured JSON) and call summaries.
- Privacy is enforced in the database: the guardian sees flagged calls and their own seniors' data via RLS, not a log of everything.
- Consent is explicit: the senior accepts a consent screen at pairing. Production would also play a recording/analysis announcement at the start of each call (two-party-consent states).
- Production path: port the senior's real number to Twilio so scam calls reach TROT automatically. SMS screening would come via a native Android app or carrier partnership.
