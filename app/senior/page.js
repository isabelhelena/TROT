import { requireProfile } from '@/lib/profile';
import CalmScreen from './calm-screen';
export default async function SeniorPage() {
  const { supabase, profile } = await requireProfile('senior');
  const result = profile.guardian_id ? await supabase.from('profiles').select('name,phone').eq('id', profile.guardian_id).maybeSingle() : { data: null };
  return <CalmScreen profile={profile} guardian={result.data} />;
}
