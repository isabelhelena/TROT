`# Phase 3 Frontend Guide: Auth, Pairing & Realtime Dashboards

> **Target Audience:** Frontend Teammate & AI Copilot Agent  
> **Stack:** Next.js (App Router), Tailwind CSS, `@supabase/ssr`, `@supabase/supabase-js`

---

## 1. Executive Summary & Goals

In Phase 3, you are building the web interface for **TROT**:
1. **Authentication & Role Selection (`/login`):** Supabase Auth (Email or Google OAuth) $\rightarrow$ select role (`guardian` or `senior`).
2. **Pairing Flow (`/senior` & `/api/pair`):** 
   - Guardian generates a 6-digit pairing code.
   - Senior enters code + their real phone number, signs consent.
   - Secure route handler links the two profiles using the Supabase Service Role key.
3. **Guardian Dashboard (`/guardian`):** Real-time monitoring of calls, live transcription feed, scam alerts with an "Acknowledge" button, and suspicious numbers list with "Mark as Trusted".
4. **Senior Calm Screen (`/senior`):** Frictionless screen showing 3 simple states: **Protected** $\rightarrow$ **Active Call** $\rightarrow$ **Possible Scam** (with a big `tel:` button to call the guardian).

---

## 2. Critical Architectural Rules (Read Before Coding!)

> [!CAUTION]
> **Rule 1: Profiles CANNOT be updated from the browser client.**  
> By design in `init.sql`, the `profiles` table has **NO UPDATE policy** for regular users. All pairing and pairing-code generation **must** be executed in Next.js Route Handlers (`app/api/pair/...`) using `SUPABASE_SERVICE_ROLE_KEY`. If you attempt `supabase.from('profiles').update(...)` in the browser, it will fail silently!

> [!IMPORTANT]
> **Rule 2: Service Role vs. Anon Key Separation**
> - **Browser client:** Uses `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`. Enforces Row-Level Security (RLS). Guardians only see their own records; seniors only see theirs.
> - **Route Handlers (`/api/...`):** Use `SUPABASE_SERVICE_ROLE_KEY` (server-side only, never `NEXT_PUBLIC_`).
> - **Realtime Subscriptions:** Realtime is RLS-gated! If you subscribe to `call_transcripts` or `alerts`, you must be logged in as the guardian or senior associated with those records.

> [!TIP]
> **Rule 3: Realtime Event Handling**  
> When new transcripts arrive via Supabase Realtime, **append the new row directly to local state** (`setTranscripts(prev => [...prev, newRow])`). **Do NOT refetch the table** on every event, as this introduces lag and ruins the live demo.

> [!WARNING]
> **Rule 4: Multi-User Browser Testing**  
> Supabase Auth shares `localStorage` across tabs in the same browser window. To test Guardian and Senior simultaneously, use **two different browser profiles** or **one regular window + one Incognito window**.

---

## 3. Dependencies Setup

Run in the project root:
```bash
npm install @supabase/supabase-js @supabase/ssr lucide-react
```

Ensure `.env` contains:
```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ... (Publishable / Anon key)
SUPABASE_SERVICE_ROLE_KEY=eyJ...      (Secret / Service role key)
```

---

## 4. Directory & File Blueprint

```
app/
├── login/
│   └── page.jsx                 # Auth (Email / Google) + Role selection modal
├── guardian/
│   └── page.jsx                 # Live dashboard (calls, transcripts, alerts, numbers)
├── senior/
│   └── page.jsx                 # Pairing input -> Consent screen -> Calm status screen
├── api/
│   └── pair/
│       ├── generate/
│       │   └── route.js         # POST: generates single-use pairing_code for guardian
│       └── route.js             # POST: links senior to guardian by code + stores phone
lib/
└── supabase/
    ├── client.js                # Browser client (createBrowserClient)
    ├── server.js                # Server Component client (createServerClient)
    └── admin.js                 # Service role client for route handlers
```

---

## 5. Implementation Code Snippets

### A. Supabase Admin Client (`lib/supabase/admin.js`)
*Used strictly inside route handlers.*

```javascript
import { createClient } from '@supabase/supabase-js';

export function createAdminClient() {
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || process.env.SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl || !serviceKey) {
    throw new Error('Missing Supabase Service Role credentials');
  }

  return createClient(supabaseUrl, serviceKey, {
    auth: { persistSession: false },
  });
}
```

### B. Supabase Browser Client (`lib/supabase/client.js`)
*Used in Client Components (`"use client"`).*

```javascript
import { createBrowserClient } from '@supabase/ssr';

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  );
}
```

---

### C. Route Handlers for Pairing

#### 1. Generate Pairing Code (`app/api/pair/generate/route.js`)
Called by the Guardian dashboard.
```javascript
import { NextResponse } from 'next/server';
import { createAdminClient } from '@/lib/supabase/admin';

export async function POST(request) {
  try {
    const { guardianId } = await request.json();
    if (!guardianId) {
      return NextResponse.json({ error: 'Missing guardianId' }, { status: 400 });
    }

    const admin = createAdminClient();
    // Generate simple 6-character code
    const pairingCode = Math.random().toString(36).substring(2, 8).toUpperCase();

    const { error } = await admin
      .from('profiles')
      .update({ pairing_code: pairingCode })
      .eq('id', guardianId);

    if (error) throw error;

    return NextResponse.json({ pairingCode });
  } catch (err) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
```

#### 2. Link Senior to Guardian (`app/api/pair/route.js`)
Called by Senior screen with `code`, `seniorId`, `realPhone`.
```javascript
import { NextResponse } from 'next/server';
import { createAdminClient } from '@/lib/supabase/admin';

export async function POST(request) {
  try {
    const { seniorId, code, phone } = await request.json();
    if (!seniorId || !code || !phone) {
      return NextResponse.json({ error: 'Missing required fields' }, { status: 400 });
    }

    // Normalize phone to E.164 (ensure leading +)
    const normalizedPhone = phone.startsWith('+') ? phone : `+1${phone.replace(/\D/g, '')}`;

    const admin = createAdminClient();

    // 1. Find guardian with this code
    const { data: guardian, error: findError } = await admin
      .from('profiles')
      .select('id')
      .eq('pairing_code', code.trim().toUpperCase())
      .eq('role', 'guardian')
      .single();

    if (findError || !guardian) {
      return NextResponse.json({ error: 'Invalid or expired pairing code' }, { status: 404 });
    }

    // 2. Link senior to guardian, set phone, clear code on guardian
    const { error: updateSeniorError } = await admin
      .from('profiles')
      .update({
        guardian_id: guardian.id,
        phone: normalizedPhone,
        consented_at: new Date().toISOString(),
      })
      .eq('id', seniorId);

    if (updateSeniorError) throw updateSeniorError;

    // 3. Clear pairing code
    await admin.from('profiles').update({ pairing_code: null }).eq('id', guardian.id);

    return NextResponse.json({ success: true, guardianId: guardian.id });
  } catch (err) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
```

---

## 6. Page Specifications

### A. Auth & Role Selection (`app/login/page.jsx`)
- Email passwordless magic-link / password sign-in (or Google OAuth).
- Upon sign-in, check if user exists in `profiles`.
- If not in `profiles`, show modal: **"I am a Guardian"** vs. **"I am a Senior"**.
- User selection inserts their initial row via browser client:
  ```javascript
  const { error } = await supabase.from('profiles').insert({
    id: user.id,
    role: selectedRole, // 'guardian' or 'senior'
    name: name,
  });
  ```
  *(Permitted by RLS policy `profiles_insert`)*.
- Redirects to `/guardian` or `/senior`.

---

### B. Guardian Dashboard (`app/guardian/page.jsx`)
Features required:
1. **Pairing Status:**
   - If no linked senior (`profiles` where `guardian_id = user.id`), show a button **"Generate Pairing Code"** that calls `/api/pair/generate`.
   - Realtime listener on `profiles` updates the UI automatically when senior connects!
2. **Live Call Status Bar:**
   - Shows active call status: `ringing`, `in_progress`, or `idle`.
   - Displays caller's number (`from_number`).
3. **Live Transcript Panel (Demo Showcase):**
   - Subscribes to `call_transcripts` via Supabase Realtime:
     ```javascript
     useEffect(() => {
       const channel = supabase
         .channel('transcripts')
         .on(
           'postgres_changes',
           { event: 'INSERT', schema: 'public', table: 'call_transcripts' },
           (payload) => {
             setTranscripts((prev) => [...prev, payload.new]);
           }
         )
         .subscribe();
       return () => { supabase.removeChannel(channel); };
     }, []);
     ```
   - Automatically auto-scrolls to the bottom.
4. **Alerts Feed:**
   - Displays scam alerts from `alerts` table (`scam_type`, `confidence`, `summary`, `created_at`).
   - "Acknowledge" button:
     ```javascript
     await supabase.from('alerts').update({ acknowledged: true }).eq('id', alertId);
     ```
5. **Suspicious Numbers Table:**
   - Queries `numbers` table ordered by `threat_count desc`.
   - Action button: **"Mark as Trusted"**:
     ```javascript
     await supabase.from('numbers').update({ status: 'trusted' }).eq('id', numberId);
     ```

---

### C. Senior Calm Screen (`app/senior/page.jsx`)
Designed for an elderly user: large fonts, high contrast, zero clutter.

1. **Step 1: Setup & Consent (if not paired):**
   - Enter 6-digit Code + Phone number.
   - Screen flips to explicit Consent: *"TROT will monitor incoming calls for fraud and alert your guardian if danger is detected."* $\rightarrow$ Button: **"I Agree & Activate"**.
2. **Step 2: Protected State (Normal):**
   - Big green badge: 🛡️ **"You are protected"**
   - Subtext: *"Incoming calls to your TROT number will ring your phone normally."*
3. **Step 3: Active Call State:**
   - Shows phone ringing / call in progress.
4. **Step 4: Possible Scam State (Triggered in real-time):**
   - If `calls.risk === 'scam'` or an alert row exists for the active call:
   - Screen flips to high-visibility amber/red banner:  
     ⚠️ **"Possible Scam Call Detected"**
   - Big clickable button:  
     `<a href="tel:+1GUARDIAN_PHONE" className="bg-red-600 ...">Call Guardian Now</a>`

---

## 7. Realtime Verification Checklist for Demo

Before demonstrating Phase 3:
- [ ] Log in as Guardian in Chrome window $\rightarrow$ see Guardian Dashboard.
- [ ] Log in as Senior in Chrome Incognito window $\rightarrow$ enter pairing code $\rightarrow$ accept consent.
- [ ] Guardian dashboard immediately reflects the paired senior without manual page refresh.
- [ ] Simulate or place a call:
  - Transcript lines appear line-by-line on Guardian dashboard.
  - When an alert is inserted, Guardian dashboard lights up with the alert box.
  - Senior screen flips from green "Protected" to red "Possible Scam Call" with the `tel:` button.

## Hackathon implementation scope (agreed October 4, 2026)

The implementation uses the reduced scope documented in the root README:
email/password login for two pre-linked accounts; guardian call/transcript/alert
views; senior ready/active/warning states; initial snapshots plus scoped Realtime;
and `backend/scripts/demo_calls.py` replay/reset commands. Signup, OAuth, role
selection, pairing endpoints, and suspicious-number management are deferred.
The pairing examples above are planning material and are not implemented.
The existing voice bridge and database schema remain unchanged. Real transcript,
call lifecycle, and detection producers are separate backend work; simulated
replay verifies the frontend without those dependencies.
