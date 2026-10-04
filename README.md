# TROT

Threat Reduction and Oversight Technology — RowdyHacks 2026.

Phase 3 provides email/password login for existing accounts, guardian-managed pairing, a guardian
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
there is no signup or role picker in this demo.

The senior must already have `phone`, `twilio_number`, and `consented_at` set.
The guardian can connect the account from the dashboard using the senior’s email. Set the guardian's `profiles.phone` to an E.164 number for the
senior's “Call Guardian” button. These are manual setup steps, not frontend edits.

Use a normal browser window for the guardian and an incognito window for the
senior, so their sessions remain separate.

## Guardian-managed pairing

Keep `SUPABASE_SERVICE_ROLE_KEY` in the server environment; never use a public
variable for it. No new tables or columns are needed.

1. Sign in as the guardian and open **Connect a senior** on `/guardian`.
2. Enter the existing senior account’s email and select **Connect senior**.
3. Sign in as the senior in a separate browser profile or incognito window.
   The senior enters no pairing code or phone number. While unlinked, the screen
   says **Waiting for your guardian**; after connection it shows the normal status.

The connection is saved in `profiles.guardian_id` and survives sign-out. Accounts,
phone setup, and consent must be prepared beforehand. This flow does not create
accounts or consent. Seniors connected to another guardian cannot be reassigned.

For a repeatable demo, set `DEMO_SENIOR_ID=<senior-profile-uuid>` in root `.env`
and restart Next.js. The connected guardian can select **Reset demo pairing**,
confirm, and reconnect using the same email while the senior stays signed in.
Reset preserves phone numbers, consent, and call history. Pairing changes are
blocked during an active call. Both screens refresh automatically via Realtime
with a five-second fallback. Replay a new demo call after reconnecting;
historical calls retain their original guardian association.

## Dashboard behavior

- Guardian: `/guardian` shows active call status, caller number, transcript,
  call-specific alerts with acknowledgement, and the last 30 calls.
- Senior: `/senior` shows ready, active call, or possible scam. Only an active
  call's risk/alerts can trigger a warning. Completed calls return to ready.
- Initial rows are loaded before live changes are merged. Events are scoped to
  the signed-in guardian/senior, deduplicated by row ID, and displayed by call SID.
  Snapshot loads buffer incoming events to avoid missing rows during loading.
- Reconnects and returning to the browser tab reload the snapshot. While visible,
  both dashboards also reconcile every five seconds so missed Realtime events do
  not require a manual page refresh. Snapshot requests do not overlap. The
  connection indicator shows Live for a subscribed channel and Auto-refresh
  when the channel is unavailable. The initial transcript load
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

## Guardian remote hangup

On a real active call, the guardian dashboard shows **End call**. Select it, then
confirm **Yes, end this call** to disconnect the conversation. **Keep call** cancels
without affecting the phone call. This control does not block future calls from
that number. Simulated `DEMO_` calls still finish through replay/reset scripts.

The Next.js server needs `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and
`SUPABASE_SERVICE_ROLE_KEY` from the root `.env` (already in `.env.example`).
Restart Next.js after changing these. These keys are server-only; never prefix
with `NEXT_PUBLIC_`. No additional packages or database schema changes are needed.

`POST /api/calls/end` validates the signed-in guardian, checks call ownership
through RLS and explicit filtering, then sends a Twilio call update. Only after
Twilio confirms completion does it mark that call completed in Supabase. Failed
hangup requests leave the stored status untouched; database sync failures after a
successful hangup are reported separately. The Python backend is unchanged.

Test with a consenting caller and the protected person's phone: answer a real
bridged call, sign in as its guardian, select End call, test Keep call once, then
confirm ending it. Both phones should disconnect and both dashboards should
return to idle/ready. No live call is disconnected by local automated tests.

```bash
node --test tests/end-call.test.mjs
```

API reference: [Twilio call updates](https://www.twilio.com/docs/voice/api/call-resource#update-a-call-resource).


## Guardian-managed pairing and repeatable demo

The senior only signs in. An unpaired senior sees **Waiting for your guardian**;
there are no pairing codes, email-entry forms, or invitation steps on that screen.
On the guardian dashboard, expand **Connect a senior**, enter the senior's existing
Supabase Auth account email, and select **Connect senior**. Both screens refresh
their connection through Realtime, with a five-second fallback check.

Pairing is saved in `profiles.guardian_id` and persists across logins. The existing
senior profile must already have consent and phone setup; the guardian cannot
create consent on someone else's behalf. Accounts and Twilio numbers are not
created by this flow. A senior linked to another guardian cannot be reassigned.

To repeat the demo, configure `DEMO_SENIOR_ID` in root `.env` and restart Next.js.
The guardian can select **Reset demo pairing** and confirm. Reset is limited to
the configured demo senior connected to that guardian. It removes the connection
and clears the guardian's unused pairing code, preserving phone numbers, consent,
and all historical call data. Changing pairing is blocked while that senior has
an active call. A reset does not run automatically when you sign out.

Demo sequence:
1. Sign in as guardian and senior in separate browser profiles.
2. Guardian resets the demo pairing; senior returns to the waiting screen.
3. Guardian enters the senior's account email and selects Connect senior.
4. Senior returns to ready with their guardian's call button, without typing.
5. Sign out/in to verify the connection remains saved.

The Next.js routes `/api/pair` and `/api/pair/reset` validate the guardian's
session and use the existing server-only Supabase service key. There are no
Python backend or database schema changes. These actions update only the pairing
fields when you use the controls; automated tests use a fake database.

```bash
node --test tests/pairing.test.mjs
```
