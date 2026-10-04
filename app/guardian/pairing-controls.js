'use client';
import { useState } from 'react';

export default function PairingControls({ seniors, demoSeniorId, activeCall }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [confirmReset, setConfirmReset] = useState(false);
  const demo = seniors.find((senior) => senior.id === demoSeniorId);
  async function send(path, body) {
    setBusy(true); setError(''); setMessage('');
    try {
      const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not update connection.');
      setMessage(result.message); setConfirmReset(false);
      window.dispatchEvent(new Event('trot-pairing-changed'));
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <details className="pairing-panel" open={!seniors.length}>
    <summary>Connect a senior <span className="muted small">Guardian-managed pairing</span></summary>
    <div className="pairing-content"><p className="muted small">Enter their existing account email. They only need to sign in—no codes or extra typing.</p>
      <form className="pairing-form" onSubmit={(event) => {
        event.preventDefault();
        if (!busy && !activeCall) send('/api/pair', { email: new FormData(event.currentTarget).get('email') });
      }}><label htmlFor="senior-email">Senior’s account email</label><div className="pairing-input-row"><input id="senior-email" name="email" type="email" autoComplete="off" placeholder="senior@example.com" required disabled={busy} /><button disabled={busy || activeCall}>{busy ? 'Updating…' : 'Connect senior'}</button></div></form>
      {demo && <div className="demo-pairing-reset">{confirmReset ? <><p>Reset this demo connection? Phone setup, consent, and call history will be kept.</p><div className="hangup-actions"><button className="secondary" disabled={busy || activeCall} onClick={() => send('/api/pair/reset', { seniorId: demo.id })}>Yes, reset demo pairing</button><button className="secondary" disabled={busy} onClick={() => setConfirmReset(false)}>Keep connection</button></div></> : <button className="secondary" disabled={busy || activeCall} onClick={() => setConfirmReset(true)}>Reset demo pairing</button>}</div>}
      {activeCall && <p className="muted small">Pairing can be changed after the active call ends.</p>}
      {message && <p role="status" className="pairing-message">{message}</p>}
      {error && <p role="alert" className="error">{error}</p>}
    </div>
  </details>;
}
