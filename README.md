# TROT

Threat Reduction and Oversight Technology — RowdyHacks 2026.

Phase 3 provides email/password login for existing pre-linked accounts, a guardian
call dashboard, a senior status screen, and scripts for a simulated call demo.
The existing Python voice bridge is preserved. This phase does not add audio
streaming, transcription providers, Gemini, recording, or number provisioning.

## Frontend setup

```bash
npm install
npm run dev
```

Add these to your existing root `.env` (or `.env.local` for Next.js), using values
from your Supabase project. Keep your existing backend variables.

```dotenv
NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<publishable-key>
```

The legacy `NEXT_PUBLIC_SUPABASE_ANON_KEY` is also supported instead of the
publishable key. Never put the service role key in a `NEXT_PUBLIC_` variable.
Restart Next.js after changing environment variables.

Open `http://localhost:3000/login`. Use your two existing confirmed Supabase Auth
users with email/password sign-in enabled and passwords set. Their `profiles.id`
values must match their Auth user IDs. The profile role determines the dashboard;
there is no signup, role picker, or pairing UI in this demo.

The senior must already have `guardian_id`, `phone`, `twilio_number`, and
`consented_at` set. Set the guardian's `profiles.phone` to an E.164 number for the
senior's “Call Guardian” button. These are manual setup steps, not frontend edits.

Use a normal browser window for the guardian and an incognito window for the
senior, so their sessions remain separate.

## Dashboard behavior

- Guardian: `/guardian` shows active call status, caller number, transcript,
  call-specific alerts with acknowledgement, and the last 30 calls.
- Senior: `/senior` shows ready, active call, or possible scam. Only an active
  call's risk/alerts can trigger a warning. Completed calls return to ready.
- Initial rows are loaded before live changes are merged. Events are scoped to
  the signed-in guardian/senior, deduplicated by row ID, and displayed by call SID.
  Snapshot loads buffer incoming events to avoid missing rows during loading.
- Reconnects and returning to the browser tab reload the snapshot. The connection
  indicator reports whether realtime is connected. The initial transcript load
  is limited to 1,000 rows across the last 30 calls for this hackathon.
- Simulated calls are visibly labeled on both screens. Acknowledging an alert
  marks it reviewed; it does not dismiss the senior's active warning.
- There is no suspicious-number management in this reduced scope.

The existing schema must be deployed, including SELECT/UPDATE policies and the
Realtime publication for `calls`, `call_transcripts`, and `alerts`. No schema
changes are required. `schema.sql` and `init.sql` are the same currently; do not
rerun the whole schema on an already initialized project.

## Simulated demo and reset

Activate your existing Python environment and install backend dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
```

The scripts use the backend's existing `SUPABASE_URL` and
`SUPABASE_SERVICE_ROLE_KEY`. Add the pre-linked senior profile UUID to root `.env`:

```dotenv
DEMO_SENIOR_ID=<senior-profile-uuid>
```

With both users logged in, run from the repo root:

```bash
python -m backend.scripts.demo_calls replay --dry-run
python -m backend.scripts.demo_calls replay
```

The actual replay writes simulated data to your configured Supabase database. It
creates a new `DEMO_` call identifier, waits 3 seconds, switches to `in_progress`,
adds four transcript lines at 3-second intervals, inserts a simulated scam alert,
holds the warning for 15 seconds, then completes the call. No phone calls or AI
requests are made. Real call/profile/number records are not changed.

To give yourself more time on the warning screen:

```bash
python -m backend.scripts.demo_calls replay --interval 4 --warning-hold 30
```

A replay refuses to start if this senior already has an unfinished simulated
call. Ctrl-C attempts to complete its own simulated call. If a terminal crashes
or a network failure leaves one unfinished, inspect then reset:

```bash
python -m backend.scripts.demo_calls reset --dry-run
python -m backend.scripts.demo_calls reset
```

Reset marks only this senior's unfinished calls with the literal `DEMO_` prefix
completed and sets `ended_at`. It preserves history, transcripts, alerts,
real calls, and account pairing. You may pass `--senior-id <uuid>` instead of
setting `DEMO_SENIOR_ID`. Avoid concurrent replays for the same senior.

## Phase 3 verification checkpoint

1. Log in as guardian and senior in separate browser profiles/windows.
2. Confirm their existing connection and the senior's guardian call button.
3. Run replay: guardian sees ringing, then in progress, then transcript lines.
4. Confirm the alert appears and the senior shows “Possible scam call”.
5. Acknowledge the alert on the guardian dashboard; refresh to confirm it persists.
6. When replay finishes, confirm the senior returns to ready while guardian can
   still inspect the completed call.
7. Run replay again: old alerts/transcripts should not appear on the new call.
8. Reset an unfinished simulated call and confirm real call records are unaffected.

These steps require your running Supabase project and demo accounts. The existing
bridge currently inserts a ringing call record; answered/completed statuses,
real transcripts, and real alerts require backend producers outside this phase.
Until those exist, a real call may remain “ringing” in the dashboard after hangup.

## Local checks

```bash
npm run lint
npm run build
node --test tests/call-state.test.mjs
python -m unittest discover -s tests -p 'test_*.py'
python -m compileall -q backend
python backend/scripts/test_voice.py
```

If Turbopack cannot bind its build subprocess port in a restricted environment,
use `npm run build -- --webpack` for the production check.

The demo script tests use a fake database and never write to Supabase. The
existing voice test uses mocked backend calls and never places a phone call.

References: [Supabase SSR setup](https://supabase.com/docs/guides/auth/server-side/nextjs)
and [Realtime Postgres Changes](https://supabase.com/docs/guides/realtime/postgres-changes).
