import LoginForm from './login-form';

export default function LoginPage() {
  const configured = Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL &&
    (process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY));
  return <main className="login-shell">
    <section className="login-intro"><p className="eyebrow">TROT / FAMILY CALL OVERSIGHT</p>
      <h1>A little reassurance.<br />A closer connection.</h1>
      <p>Stay connected with the people who matter, with a clear view of incoming calls and potential concerns.</p>
      <div className="intro-note">Built for seniors. Shared with someone they trust.</div>
    </section>
    <section className="card login-card"><p className="eyebrow">WELCOME BACK</p><h2>Sign in to TROT</h2>
      <p className="muted">Use your existing guardian or senior account.</p>
      {configured ? <LoginForm /> : <p role="alert" className="error">Configure the public Supabase URL and publishable or anon key, then restart Next.js.</p>}
    </section>
  </main>;
}
