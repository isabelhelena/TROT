import 'server-only';
import { redirect } from 'next/navigation';
import { createClient } from './supabase/server';

export async function requireProfile(role) {
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL ||
      !(process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY)) {
    redirect('/login');
  }
  const supabase = await createClient();
  const { data: { user }, error: authError } = await supabase.auth.getUser();
  if (authError || !user) redirect('/login');
  const { data: profile, error } = await supabase.from('profiles').select('*').eq('id', user.id).maybeSingle();
  if (error || !profile || !['guardian', 'senior'].includes(profile.role)) redirect('/login?setup=missing');
  if (role && profile.role !== role) redirect(`/${profile.role}`);
  return { supabase, profile };
}
