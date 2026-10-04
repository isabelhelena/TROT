'use client';
import { useEffect, useState } from 'react';
import { createClient } from './supabase/client';

export function useFamilyConnection(initialProfile, initialSeniors = [], initialGuardian = null) {
  const [family, setFamily] = useState({ profile: initialProfile, seniors: initialSeniors, guardian: initialGuardian });
  const [error, setError] = useState('');
  useEffect(() => {
    const supabase = createClient();
    let alive = true, loading = false, queued = false;
    async function reload() {
      if (!alive) return;
      if (loading) { queued = true; return; }
      loading = true;
      try {
        const own = await supabase.from('profiles').select('*').eq('id', initialProfile.id).maybeSingle();
        if (own.error || !own.data) throw new Error('Could not load your connection.');
        const profile = own.data;
        let seniors = [], guardian = null;
        if (profile.role === 'guardian') {
          const result = await supabase.from('profiles').select('id,name,phone,twilio_number')
            .eq('guardian_id', profile.id).eq('role', 'senior');
          if (result.error) throw result.error;
          seniors = result.data;
        } else if (profile.guardian_id) {
          const result = await supabase.from('profiles').select('name,phone')
            .eq('id', profile.guardian_id).maybeSingle();
          if (result.error) throw result.error;
          guardian = result.data;
        }
        if (alive) { setFamily({ profile, seniors, guardian }); setError(''); }
      } catch { if (alive) setError('Could not refresh your family connection. We’ll retry shortly.'); }
      finally {
        loading = false;
        if (alive && queued) { queued = false; reload(); }
      }
    }
    let channel = supabase.channel(`family-${initialProfile.id}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'profiles', filter: `id=eq.${initialProfile.id}` }, reload);
    if (initialProfile.role === 'guardian') channel = channel.on('postgres_changes', {
      event: '*', schema: 'public', table: 'profiles', filter: `guardian_id=eq.${initialProfile.id}`,
    }, reload);
    channel.subscribe((status) => { if (status === 'SUBSCRIBED') reload(); });
    reload();
    // A reset removes a guardian's RLS visibility, so its realtime event can be
    // filtered out. A small connection-only poll handles that and reconnects.
    const timer = window.setInterval(reload, 5000);
    window.addEventListener('focus', reload);
    window.addEventListener('trot-pairing-changed', reload);
    return () => {
      alive = false; window.clearInterval(timer);
      window.removeEventListener('focus', reload);
      window.removeEventListener('trot-pairing-changed', reload);
      supabase.removeChannel(channel);
    };
  }, [initialProfile.id, initialProfile.role]);
  return { ...family, error };
}
