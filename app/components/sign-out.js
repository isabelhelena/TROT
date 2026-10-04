'use client';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabase/client';
export default function SignOut() {
  const router = useRouter();
  const [error, setError] = useState('');
  return <div><button className="secondary" onClick={async () => {
    const { error } = await createClient().auth.signOut();
    if (error) setError(error.message); else { router.replace('/login'); router.refresh(); }
  }}>Sign out</button>{error && <p role="alert">{error}</p>}</div>;
}
