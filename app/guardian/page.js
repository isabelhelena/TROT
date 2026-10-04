import { requireProfile } from '@/lib/profile';
import Dashboard from './dashboard';
export default async function GuardianPage() {
  const { supabase, profile } = await requireProfile('guardian');
  const { data: seniors, error } = await supabase.from('profiles').select('id,name,phone,twilio_number').eq('guardian_id', profile.id).eq('role', 'senior');
  return <Dashboard profile={profile} seniors={seniors || []} demoSeniorId={process.env.DEMO_SENIOR_ID || null} setupError={error ? 'Could not load linked family members.' : ''} />;
}
