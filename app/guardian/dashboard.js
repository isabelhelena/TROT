'use client';
import { useEffect, useRef, useState } from 'react';
import { useCallFeed } from '@/lib/use-call-feed';
import { currentCall, hasWarning, isDemo } from '@/lib/call-state.mjs';
import { createClient } from '@/lib/supabase/client';
import SignOut from '@/app/components/sign-out';

export default function Dashboard({ profile, seniors, setupError }) {
  const feed = useCallFeed(profile);
  const active = currentCall(feed.calls);
  const [selected, setSelected] = useState(null);
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState(null);
  const call = active || feed.calls.find((item) => item.call_sid === selected) || [...feed.calls].sort((a,b) => b.started_at.localeCompare(a.started_at))[0];
  const lines = feed.call_transcripts.filter((line) => line.call_sid === call?.call_sid).sort((a,b) => a.created_at.localeCompare(b.created_at));
  const alerts = feed.alerts.filter((alert) => alert.call_sid === call?.call_sid);
  const bottom = useRef(null);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [lines.length, call?.call_sid]);
  async function acknowledge(id) {
    setBusy(id); setActionError('');
    try {
      const { data, error } = await createClient().from('alerts').update({ acknowledged: true }).eq('id', id).select('id');
      if (error) throw error;
      if (!data?.length) throw new Error('Alert could not be acknowledged. Check account permissions.');
    } catch (err) { setActionError(err.message); }
    finally { setBusy(null); }
  }
  return <main className="dashboard">
    <header className="topbar"><div className="brand">TROT<span>Family call oversight</span></div><SignOut /></header>
    <section className="page-heading"><div><p className="eyebrow">GUARDIAN DASHBOARD</p><h1>Welcome, {profile.name || 'guardian'}.</h1><p className="muted">A clear view of your family’s calls.</p></div><span className={`badge ${feed.connection === 'Live' ? 'green' : 'amber'}`}>{feed.connection}</span></section>
    {(feed.error || setupError || actionError) && <p role="alert" className="error">{feed.error || setupError || actionError}</p>}
    <section className="family-strip"><span className="eyebrow">YOUR CONNECTIONS</span>{seniors.length ? seniors.map((senior) => <div key={senior.id}><strong>{senior.name || 'Senior'}</strong><span className="muted">{senior.twilio_number ? `TROT ${senior.twilio_number}` : 'Twilio number not assigned'}</span></div>) : <p>No senior is linked. Check the preconfigured profiles.</p>}</section>
    <div className="dashboard-grid"><div>
      <section className={`card call-card ${hasWarning(active, feed.alerts) ? 'warning-border' : ''}`}>
        <div className="section-title"><h2>{active ? 'Current call' : 'Call overview'}</h2><span className="badge">{call ? call.status.replaceAll('_',' ') : 'Idle'}</span></div>
        <h3>{call?.from_number || 'No calls yet'}</h3><p className="muted">{active ? 'A call is active. Updates appear here as they arrive.' : 'No active call. Previous calls remain available below.'}</p>
        {isDemo(call) && <span className="badge amber">SIMULATED DEMO · no phone call placed</span>}
      </section>
      <section className="card transcript-card"><div className="section-title"><h2>Conversation transcript</h2><span className="muted small">Caller audio</span></div>
        <div className="transcript" role="log" aria-label="Call transcript" aria-live="polite">{lines.length ? lines.map((line) => <div className="transcript-line" key={line.id}><span className="eyebrow">CALLER</span><p>{line.text}</p></div>) : <p className="empty">{active ? 'Waiting for transcript updates…' : 'Select a call to view its transcript.'}</p>}<div ref={bottom} /></div>
      </section>
    </div><aside>
      <section className="card"><h2>Call alerts</h2>{alerts.length ? alerts.map((alert) => <article className="alert-card" key={alert.id}><span className="eyebrow">POSSIBLE SCAM · {Math.round(Number(alert.confidence || 0)*100)}% CONFIDENCE</span><h3>{alert.scam_type?.replaceAll('_',' ') || 'Suspicious conversation'}</h3><p>{alert.summary}</p><button className="secondary" disabled={alert.acknowledged || busy === alert.id} onClick={() => acknowledge(alert.id)}>{alert.acknowledged ? 'Acknowledged' : busy === alert.id ? 'Saving…' : 'Acknowledge'}</button></article>) : <p className="empty">No alerts for this call.</p>}</section>
      <section className="card history"><h2>Recent calls</h2>{[...feed.calls].sort((a,b) => b.started_at.localeCompare(a.started_at)).map((item) => <button className="history-item" disabled={Boolean(active)} aria-pressed={item.call_sid === call?.call_sid} key={item.id} onClick={() => setSelected(item.call_sid)}><strong>{isDemo(item) ? 'Demo call' : item.from_number}</strong><span>{item.status.replaceAll('_',' ')} · {new Date(item.started_at).toLocaleTimeString()}</span></button>)}{!feed.calls.length && <p className="empty">Your calls will appear here.</p>}</section>
    </aside></div>
  </main>;
}
