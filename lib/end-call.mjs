const reply = (body, status = 200) => Response.json(body, {
  status, headers: { 'Cache-Control': 'no-store' },
});

/** Dependencies are supplied by the server route; tests never contact Twilio. */
export async function handleEndCall(request, { getUserClient, getAdminClient, stopCall }) {
  if (request.headers.get('origin') !== new URL(request.url).origin) {
    return reply({ error: 'This action must be requested from the dashboard.' }, 403);
  }
  let callSid;
  try { ({ callSid } = await request.json()); }
  catch { return reply({ error: 'Invalid request body.' }, 400); }
  if (typeof callSid !== 'string' || !/^CA[0-9a-f]{32}$/i.test(callSid)) {
    return reply({ error: 'Select an active real phone call.' }, 400);
  }
  try {
    const supabase = await getUserClient();
    const { data: { user }, error: authError } = await supabase.auth.getUser();
    if (authError || !user) return reply({ error: 'Sign in before ending a call.' }, 401);
    const { data: profile, error: profileError } = await supabase.from('profiles')
      .select('role').eq('id', user.id).maybeSingle();
    if (profileError) return reply({ error: 'Could not verify your account.' }, 503);
    if (profile?.role !== 'guardian') return reply({ error: 'Only the guardian can end this call.' }, 403);
    // RLS plus explicit ownership: never accept a guardian ID from the browser.
    const { data: call, error: callError } = await supabase.from('calls')
      .select('id,call_sid,status,ended_at').eq('call_sid', callSid)
      .eq('guardian_id', user.id).maybeSingle();
    if (callError) return reply({ error: 'Could not verify the selected call.' }, 503);
    if (!call) return reply({ error: 'Call not found for your account.' }, 404);
    if (call.ended_at || !['ringing', 'in_progress'].includes(call.status)) {
      return reply({ error: 'This call has already ended. Refresh the dashboard.' }, 409);
    }
    // Check server configuration before sending the irreversible hangup request.
    const admin = getAdminClient();
    try { await stopCall(callSid); }
    catch { return reply({ error: 'Could not confirm the hangup with Twilio. The call may still be active; check before retrying.' }, 502); }
    console.info('[GUARDIAN_HANGUP] CallSid=%s', callSid);
    let synced = false;
    try {
      const { data, error } = await admin.from('calls')
        .update({ status: 'completed', ended_at: new Date().toISOString() })
        .eq('id', call.id).eq('guardian_id', user.id)
        .in('status', ['ringing', 'in_progress']).select('id');
      if (error) throw error;
      synced = Boolean(data?.length);
      // A Twilio callback may have completed the row before this update.
      if (!synced) {
        const result = await supabase.from('calls').select('status,ended_at')
          .eq('id', call.id).eq('guardian_id', user.id).maybeSingle();
        synced = !result.error && Boolean(result.data?.ended_at);
      }
    } catch { console.warn('[GUARDIAN_HANGUP_SYNC_PENDING] CallSid=%s', callSid); }
    return reply({ success: true, synced, message: synced ? 'Call ended.' : 'Twilio confirmed the hangup. Database status sync is pending.' });
  } catch {
    return reply({ error: 'Call controls are unavailable. Check server configuration and try again.' }, 503);
  }
}
