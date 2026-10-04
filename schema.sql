-- =====================================================================
-- TROT schema (voice-only). Paste into the Supabase SQL editor.
-- All phone numbers are stored in E.164 format (+12105551234).
-- The Python backend and Next.js route handlers use the SERVICE ROLE
-- key, which bypasses RLS. The browser uses the anon key + RLS.
-- =====================================================================

-- ---------- profiles ----------
-- One row per auth user. Created by the role picker after first login.
create table profiles (
  id             uuid primary key references auth.users(id) on delete cascade,
  role           text not null check (role in ('guardian', 'senior')),
  name           text,
  phone          text unique,          -- senior: real phone (Twilio <Dial> target). guardian: optional, for alert calls
  twilio_number  text unique,          -- senior only: their TROT number (assign by hand)
  guardian_id    uuid references profiles(id) on delete set null,  -- senior only
  pairing_code   text unique,          -- guardian only: single-use, cleared once claimed
  consented_at   timestamptz,          -- senior only: set when they accept the consent screen
  created_at     timestamptz not null default now()
);

-- ---------- calls ----------
create table calls (
  id           uuid primary key default gen_random_uuid(),
  call_sid     text not null unique,   -- Twilio CallSid
  senior_id    uuid not null references profiles(id) on delete cascade,
  guardian_id  uuid not null references profiles(id) on delete cascade,
  from_number  text not null,          -- true caller, from the webhook's From field
  status       text not null default 'ringing'
               check (status in ('ringing', 'in_progress', 'completed', 'no_answer', 'busy', 'failed')),
  risk         text not null default 'none'
               check (risk in ('none', 'suspicious', 'scam')),
  summary      text,                   -- Gemini's plain-language summary, filled in at the end
  started_at   timestamptz not null default now(),
  ended_at     timestamptz
);

-- ---------- call_transcripts ----------
-- One row per final Deepgram utterance (caller's side of the call).
create table call_transcripts (
  id           uuid primary key default gen_random_uuid(),
  call_sid     text not null references calls(call_sid) on delete cascade,
  senior_id    uuid not null references profiles(id) on delete cascade,
  guardian_id  uuid not null references profiles(id) on delete cascade,
  text         text not null,
  created_at   timestamptz not null default now()
);

-- ---------- alerts ----------
create table alerts (
  id             uuid primary key default gen_random_uuid(),
  call_sid       text not null references calls(call_sid) on delete cascade,
  senior_id      uuid not null references profiles(id) on delete cascade,
  guardian_id    uuid not null references profiles(id) on delete cascade,
  contact_number text not null,
  scam_type      text,                 -- e.g. 'grandchild_in_jail', 'bank_impersonation', 'tech_support'
  severity       text not null default 'high' check (severity in ('medium', 'high')),
  confidence     numeric,
  trigger        text check (trigger in ('keyword', 'heartbeat')),  -- what caused the LLM check that fired
  summary        text,                 -- "why we flagged this", shown to the guardian
  acknowledged   boolean not null default false,
  created_at     timestamptz not null default now()
);

-- ---------- numbers ----------
-- Per-senior reputation list. Powers "most suspicious numbers" and
-- the guardian's "mark as trusted" button (trusted numbers skip analysis).
create table numbers (
  id           uuid primary key default gen_random_uuid(),
  senior_id    uuid not null references profiles(id) on delete cascade,
  guardian_id  uuid not null references profiles(id) on delete cascade,
  number       text not null,
  status       text not null default 'unknown'
               check (status in ('unknown', 'trusted', 'suspicious')),
  threat_count int not null default 0,
  last_seen    timestamptz not null default now(),
  unique (senior_id, number)
);

-- ---------- indexes ----------
create index calls_guardian_idx       on calls (guardian_id, started_at desc);
create index calls_senior_idx         on calls (senior_id, started_at desc);
create index transcripts_call_idx     on call_transcripts (call_sid, created_at);
create index alerts_guardian_idx      on alerts (guardian_id, created_at desc);
-- One alert per call. The keyword trigger and the heartbeat can race, so the
-- backend inserts with ON CONFLICT (call_sid) DO NOTHING.
create unique index alerts_one_per_call on alerts (call_sid);
create index numbers_threat_idx       on numbers (senior_id, threat_count desc);
create index profiles_twilio_idx      on profiles (twilio_number);

-- =====================================================================
-- Row Level Security
-- =====================================================================
alter table profiles          enable row level security;
alter table calls             enable row level security;
alter table call_transcripts  enable row level security;
alter table alerts            enable row level security;
alter table numbers           enable row level security;

-- Helper: returns the current user's guardian_id (if they are a senior).
-- SECURITY DEFINER avoids infinite recursion when profiles policies
-- need to look at profiles.
create or replace function public.my_guardian_id()
returns uuid
language sql
security definer
set search_path = public
stable
as $$
  select guardian_id from profiles where id = auth.uid();
$$;

-- profiles: see yourself, your linked senior, and your guardian.
create policy "profiles_select" on profiles for select using (
  id = auth.uid()
  or guardian_id = auth.uid()          -- guardian sees their senior
  or id = public.my_guardian_id()      -- senior sees their guardian (for the contact button)
);

-- profiles: a user can create only their own bare profile (role picker).
-- Linking, pairing codes and twilio_number are set server-side (service role).
create policy "profiles_insert" on profiles for insert with check (
  id = auth.uid()
  and guardian_id is null
  and twilio_number is null
  and pairing_code is null
);
-- (No update policy on purpose: pairing and code generation go through route handlers.)

-- calls / transcripts: guardian and senior can read their own; only the backend writes.
create policy "calls_select" on calls for select using (
  guardian_id = auth.uid() or senior_id = auth.uid()
);
create policy "transcripts_select" on call_transcripts for select using (
  guardian_id = auth.uid() or senior_id = auth.uid()
);

-- alerts: both sides read; guardian can acknowledge.
create policy "alerts_select" on alerts for select using (
  guardian_id = auth.uid() or senior_id = auth.uid()
);
create policy "alerts_update_guardian" on alerts for update
  using (guardian_id = auth.uid())
  with check (guardian_id = auth.uid());

-- numbers: guardian manages (mark trusted / suspicious); backend upserts counts.
create policy "numbers_select_guardian" on numbers for select using (guardian_id = auth.uid());
create policy "numbers_update_guardian" on numbers for update
  using (guardian_id = auth.uid())
  with check (guardian_id = auth.uid());

-- =====================================================================
-- Realtime (off by default). RLS applies to realtime events, so
-- the select policies above are what let dashboards receive updates.
-- =====================================================================
alter publication supabase_realtime add table calls;
alter publication supabase_realtime add table call_transcripts;
alter publication supabase_realtime add table alerts;
alter publication supabase_realtime add table profiles;  -- guardian dashboard activates when senior links

-- =====================================================================
-- Phase 0 seeding (do this by hand)
-- 1. Dashboard -> Authentication -> Add user (two users: guardian, senior).
-- 2. Copy their UUIDs and run something like:
--
-- insert into profiles (id, role, name, phone) values
--   ('<GUARDIAN_UUID>', 'guardian', 'Sam', '+1XXXXXXXXXX');
-- insert into profiles (id, role, name, phone, twilio_number, guardian_id, consented_at) values
--   ('<SENIOR_UUID>', 'senior', 'Grandma', '+1YYYYYYYYYY', '+1ZZZZZZZZZZ', '<GUARDIAN_UUID>', now());
--
-- twilio_number = the number you bought in the Twilio console.
-- phone = the senior's real phone (must be verified in Twilio on a trial account).
-- =====================================================================