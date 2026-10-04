'use client';
import { useCallFeed } from '@/lib/use-call-feed';
import { currentCall, hasWarning, isDemo } from '@/lib/call-state.mjs';
import SignOut from '@/app/components/sign-out';
import AgencyBrand from '@/app/components/agency-brand';
import HorseMascot from '@/app/components/horse-mascot';
import { useFamilyConnection } from '@/lib/use-family-connection';
export default function CalmScreen({ profile: initialProfile, guardian: initialGuardian }) {
  const { profile, guardian, error: pairingError } = useFamilyConnection(initialProfile, [], initialGuardian);
  const feed = useCallFeed(profile);
  const call = currentCall(feed.calls);
  const warning = hasWarning(call, feed.alerts);
  const ready = Boolean(profile.twilio_number && profile.phone && profile.guardian_id && profile.consented_at);
  const contact = /^\+[1-9][0-9]{1,14}$/.test(guardian?.phone || '') ? guardian.phone : null;
  return <main className="senior-shell">
    <header className="topbar"><AgencyBrand subtitle="Here with you" /><SignOut /></header>
    <section className={`calm-card ${warning ? 'calm-warning' : 'calm-ready'}`} aria-live="polite">
      <p className="eyebrow">HELLO, {profile.name || 'FRIEND'}</p>
      <div className="calm-symbol agency-companion" aria-hidden="true"><HorseMascot attentive={Boolean(call)} /><span className="companion-status">{warning ? '!' : call ? '☎' : '✓'}</span></div>
      <h1>{warning ? 'Possible scam call' : call ? 'You have an active call' : !profile.guardian_id ? 'Waiting for your guardian' : ready ? 'Ready for your calls' : 'Setup needs attention'}</h1>
      <p>{warning ? 'Take your time. Do not share passwords or send money. You can hang up and call someone you trust.' : call ? (call.status === 'ringing' ? 'Your phone is ringing.' : 'Your call is in progress.') : !profile.guardian_id ? 'You’re signed in. Your guardian will connect your account.' : ready ? 'Incoming calls to your TROT number will ring your phone normally.' : 'Ask your guardian to check your linked account, phone number, and consent setup.'}</p>
      {isDemo(call) && <p className="demo-note">Simulated demo call</p>}
      {contact ? <a className="guardian-call" href={`tel:${contact}`}>Call {guardian.name || 'your guardian'}</a> : profile.guardian_id ? <p className="muted">Your guardian’s phone number has not been configured.</p> : null}
    </section>
    {pairingError && <p role="alert" className="error">{pairingError}</p>}
    <p className="companion-caption"></p>
    <p className="connection-note">{feed.connection === 'Live' ? 'Connected to call updates' : 'Reconnecting to call updates…'}{feed.error && <span role="alert"> — {feed.error}</span>}</p>
  </main>;
}
