import { createClient } from '@/lib/supabase/server';
import { createAdminClient } from '@/lib/supabase/admin';
import { stopCall } from '@/lib/twilio-call-control';
import { handleEndCall } from '@/lib/end-call.mjs';

export const runtime = 'nodejs';

export async function POST(request) {
  return handleEndCall(request, {
    getUserClient: createClient, getAdminClient: createAdminClient, stopCall,
  });
}
