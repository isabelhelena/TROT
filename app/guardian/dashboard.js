'use client';
import { useEffect, useRef, useState } from 'react';
import { useCallFeed } from '@/lib/use-call-feed';
import { currentCall, hasWarning, isDemo } from '@/lib/call-state.mjs';
import { createClient } from '@/lib/supabase/client';
import SignOut from '@/app/components/sign-out';
import AgencyBrand from '@/app/components/agency-brand';
import AgencyIcon from '@/app/components/agency-icon';
import CaseFolder from '@/app/components/case-folder';
import PairingControls from './pairing-controls';
import { useFamilyConnection } from '@/lib/use-family-connection';

export default function Dashboard({ profile, seniors: initialSeniors, setupError, demoSeniorId }) {
  const family = useFamilyConnection(profile, initialSeniors);
  const seniors = family.seniors;
  const feed = useCallFeed(profile);
  const [endedCalls, setEndedCalls] = useState([]);
  const displayedCalls = feed.calls.map((item) => endedCalls.includes(item.call_sid) ? { ...item, status: 'completed' } : item);
  const active = currentCall(displayedCalls);
  const [confirmSid, setConfirmSid] = useState(null);
  const [ending, setEnding] = useState(false);
  const [callMessage, setCallMessage] = useState('');
  const [selected, setSelected] = useState(null);
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState(null);
  const call = active || displayedCalls.find((item) => item.call_sid === selected) || [...displayedCalls].sort((a,b) => b.started_at.localeCompare(a.started_at))[0];
  const lines = feed.call_transcripts.filter((line) => line.call_sid === call?.call_sid).sort((a,b) => a.created_at.localeCompare(b.created_at));
  const alerts = feed.alerts.filter((alert) => alert.call_sid === call?.call_sid);
  const bottom = useRef(null);
  const urgentTranscript = hasWarning(active, feed.alerts);
  useEffect(() => {
    if (bottom.current?.closest('details')?.open) bottom.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [lines.length, call?.call_sid]);
  async function acknowledge(id) {
    setBusy(id); setActionError('');
    try {
      const { data, error } = await createClient().from('alerts').update({ acknowledged: true }).eq('id', id).select('id');
      if (error) throw error;
      if (!data?.length) throw new Error('Alert could not be acknowledged. Check account permissions.');
    } catch (err) { setActionError(err.message); }
    finally { setBusy(null); }
  }
  async function endCall() {
    if (!active || confirmSid !== active.call_sid || ending) return;
    const sid = active.call_sid;
    setEnding(true); setActionError(''); setCallMessage('');
    try {
      const response = await fetch('/api/calls/end', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ callSid: sid }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not end the call.');
      setEndedCalls((previous) => [...previous, sid]);
      setSelected(sid); setConfirmSid(null); setCallMessage(result.message);
    } catch (err) { setActionError(err.message); }
    finally { setEnding(false); }
  }
  return <main className="dashboard">
    <header className="topbar"><AgencyBrand subtitle="Family call oversight" /><SignOut /></header>
    <section className="page-heading"><div><p className="eyebrow">GUARDIAN DASHBOARD</p><h1>Welcome, {profile.name || 'guardian'}.</h1><p className="muted">A clear view of your family’s calls.</p></div><span className={`badge ${feed.connection === 'Live' ? 'green' : 'amber'}`}>{feed.connection}</span></section>
    {(feed.error || family.error || setupError || actionError) && <p role="alert" className="error">{feed.error || family.error || setupError || actionError}</p>}
    <section className="family-strip"><span className="eyebrow agency-heading"><AgencyIcon kind="horseshoe" />YOUR CONNECTIONS</span>{seniors.length ? seniors.map((senior) => <div key={senior.id}><strong>{senior.name || 'Senior'}</strong><span className="muted">{senior.twilio_number ? `TROT ${senior.twilio_number}` : 'Twilio number not assigned'}</span></div>) : <p>No senior is linked yet. Use Connect a senior below.</p>}</section>
    <PairingControls seniors={seniors} demoSeniorId={demoSeniorId} activeCall={Boolean(active)} />
    <div className="dashboard-overview">
      <section className={`card call-card ${hasWarning(active, feed.alerts) ? 'warning-border' : ''}`}>
        <div className="section-title"><h2>{active ? 'Current call' : 'Call overview'}</h2>{active && <span className="badge">{active.status.replaceAll('_',' ')}</span>}</div>
        <h3>{active ? active.from_number : 'No active calls'}</h3><p className="muted">{active ? 'A call is active. Updates appear here as they arrive.' : 'Incoming calls will appear here.'}</p>
        {isDemo(active) && <span className="badge amber">SIMULATED DEMO · no phone call placed</span>}
        {active && !isDemo(active) && <div className="call-controls">
          {confirmSid === active.call_sid ? <div className="hangup-confirm" role="group" aria-label="Confirm ending this call">
            <p>End the call from <strong>{active.from_number}</strong>? Both people will be disconnected.</p>
            <div className="hangup-actions"><button className="end-call-button" disabled={ending} onClick={endCall}>{ending ? 'Ending call…' : 'Yes, end this call'}</button><button className="secondary" disabled={ending} onClick={() => setConfirmSid(null)}>Keep call</button></div>
          </div> : <button className="end-call-button" disabled={ending} onClick={() => { setActionError(''); setCallMessage(''); setConfirmSid(active.call_sid); }}>End call</button>}
        </div>}
        {callMessage && <p className="call-control-message" role="status">{callMessage}</p>}
      </section>
      <section className="card"><p className="eyebrow folio-label">ON THE LOOKOUT</p><h2 className="agency-heading"><AgencyIcon />Call alerts</h2>{alerts.length ? alerts.map((alert) => <article className="alert-card" key={alert.id}><span className="eyebrow">POSSIBLE SCAM · {Math.round(Number(alert.confidence || 0)*100)}% CONFIDENCE</span><h3>{alert.scam_type?.replaceAll('_',' ') || 'Suspicious conversation'}</h3><p>{alert.summary}</p><button className="secondary" disabled={alert.acknowledged || busy === alert.id} onClick={() => acknowledge(alert.id)}>{alert.acknowledged ? 'Acknowledged' : busy === alert.id ? 'Saving…' : 'Acknowledge'}</button></article>) : <p className="empty agency-all-clear"><AgencyIcon />No alerts for this call.<span className="agency-aside">Nothing suspicious in the case notes.</span></p>}</section>
    </div>
    <section className="case-files" aria-labelledby="case-files-heading">
      <div className="case-files-heading"><h2 id="case-files-heading">Your case files</h2><p className="muted small">Open a folder to review the details.</p></div>
      <div className="case-folders">
      <CaseFolder className="transcript-card" title="Conversation transcript" tab="FIELD NOTES"
        description={`${lines.length} transcript ${lines.length === 1 ? 'line' : 'lines'} · caller audio`}
        urgent={urgentTranscript}
        attentionKey={urgentTranscript ? `urgent-${active.call_sid}` : selected ? `history-${selected}` : null}
        onOpen={() => bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })}>
        <div className="transcript" role="log" aria-label="Call transcript" aria-live="polite">{lines.length ? lines.map((line) => <div className="transcript-line" key={line.id}><span className="eyebrow">CALLER</span><p>{line.text}</p></div>) : <p className="empty">{active ? 'Waiting for transcript updates…' : 'Select a call to view its transcript.'}</p>}<div ref={bottom} /></div>
      </CaseFolder>
      <CaseFolder className="history" title="Recent calls" tab="THE CASE LOG" description={`${displayedCalls.length} ${displayedCalls.length === 1 ? 'call' : 'calls'} on file`}>{[...displayedCalls].sort((a,b) => b.started_at.localeCompare(a.started_at)).map((item) => <button className="history-item" disabled={Boolean(active)} aria-pressed={item.call_sid === call?.call_sid} key={item.id} onClick={() => setSelected(item.call_sid)}><strong>{isDemo(item) ? 'Demo call' : item.from_number}</strong><span>{item.status.replaceAll('_',' ')} · {new Date(item.started_at).toLocaleTimeString()}</span></button>)}{!feed.calls.length && <p className="empty">Your calls will appear here.</p>}</CaseFolder>
      </div>
    </section>
  </main>;
}
