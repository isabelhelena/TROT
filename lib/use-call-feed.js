'use client';
import { useEffect, useState } from 'react';
import { createClient } from './supabase/client';
import { mergeRow } from './call-state.mjs';

const empty = () => ({ calls: [], call_transcripts: [], alerts: [] });

export function useCallFeed(profile) {
  const [feed, setFeed] = useState(empty);
  const [connection, setConnection] = useState('Connecting');
  const [error, setError] = useState('');
  useEffect(() => {
    const supabase = createClient();
    const owner = profile.role === 'guardian' ? 'guardian_id' : 'senior_id';
    let alive = true, loading = false, pending = [], generation = 0;
    function apply(snapshot, event) {
      const rows = snapshot[event.table];
      return { ...snapshot, [event.table]: event.eventType === 'DELETE'
        ? rows.filter((row) => row.id !== event.old.id)
        : mergeRow(rows, event.new) };
    }
    function receive(event) {
      if (loading) pending.push(event);
      else setFeed((previous) => apply(previous, event));
    }
    async function load() {
      const version = ++generation;
      loading = true; pending = [];
      try {
        const result = await supabase.from('calls').select('*').eq(owner, profile.id)
          .order('started_at', { ascending: false }).limit(30);
        if (result.error) throw result.error;
        const sids = result.data.map((call) => call.call_sid);
        const results = sids.length ? await Promise.all([
          supabase.from('call_transcripts').select('*').eq(owner, profile.id).in('call_sid', sids).order('created_at').limit(1000),
          supabase.from('alerts').select('*').eq(owner, profile.id).in('call_sid', sids).order('created_at'),
        ]) : [{ data: [] }, { data: [] }];
        for (const item of results) if (item.error) throw item.error;
        if (!alive || version !== generation) return;
        let snapshot = { calls: result.data, call_transcripts: results[0].data, alerts: results[1].data };
        for (const event of pending) snapshot = apply(snapshot, event);
        pending = []; loading = false; setFeed(snapshot); setError('');
      } catch (err) {
        if (!alive || version !== generation) return;
        loading = false;
        const events = pending; pending = [];
        setFeed((previous) => events.reduce(apply, previous));
        setError(`Could not load call data: ${err.message}`);
      }
    }
    let channel = supabase.channel(`feed-${profile.id}`);
    for (const table of ['calls', 'call_transcripts', 'alerts']) {
      channel = channel.on('postgres_changes', {
        event: '*', schema: 'public', table, filter: `${owner}=eq.${profile.id}`,
      }, (payload) => receive({ ...payload, table }));
    }
    channel.subscribe((status) => {
      if (!alive) return;
      setConnection(status === 'SUBSCRIBED' ? 'Live' : 'Reconnecting');
      if (status === 'SUBSCRIBED') load();
    });
    // Initial snapshot still loads if the realtime connection is unavailable.
    load();
    const resync = () => load();
    window.addEventListener('focus', resync);
    window.addEventListener('online', resync);
    return () => {
      alive = false; generation++;
      window.removeEventListener('focus', resync);
      window.removeEventListener('online', resync);
      supabase.removeChannel(channel);
    };
  }, [profile.id, profile.role]);
  return { ...feed, connection, error };
}
