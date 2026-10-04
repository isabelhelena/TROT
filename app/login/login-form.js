'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabase/client';

export default function LoginForm() {
  const router = useRouter();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const fields = new FormData(event.currentTarget);
      const supabase = createClient();
      const { error: authError } = await supabase.auth.signInWithPassword({
        email: fields.get('email').trim(), password: fields.get('password'),
      });
      if (authError) throw authError;
      const { data: { user } } = await supabase.auth.getUser();
      const { data: profile, error: profileError } = await supabase.from('profiles').select('role').eq('id', user.id).maybeSingle();
      if (profileError || !['guardian', 'senior'].includes(profile?.role)) {
        throw new Error('Your account needs a preconfigured guardian or senior profile. Ask your teammate to check setup.');
      }
      router.replace(`/${profile.role}`);
      router.refresh();
    } catch (err) { setError(err.message); setBusy(false); }
  }
  return <form onSubmit={submit} className="login-form">
    <label>Email<input type="email" name="email" autoComplete="username" required /></label>
    <label>Password<input type="password" name="password" autoComplete="current-password" required /></label>
    {error && <p role="alert" className="error">{error}</p>}
    <button disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
    <p className="muted small">Accounts and family connections are set up ahead of the demo.</p>
  </form>;
}
