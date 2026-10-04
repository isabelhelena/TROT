import { createClient } from '@/lib/supabase/server';
import { createAdminClient } from '@/lib/supabase/admin';
import { handlePairing } from '@/lib/pairing.mjs';

export async function POST(request) {
  return handlePairing(request, { getUserClient: createClient, getAdminClient: createAdminClient }, 'connect');
}
