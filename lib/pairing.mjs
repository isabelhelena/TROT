const reply = (body, status = 200) => Response.json(body, { status, headers: { 'Cache-Control': 'no-store' } });

async function findUserByEmail(admin, email) {
  // Auth emails are not stored in profiles. Never send this directory to clients.
  for (let page = 1; page <= 50; page++) {
    const { data, error } = await admin.auth.admin.listUsers({ page, perPage: 200 });
    if (error) throw error;
    const user = data.users.find((item) => item.email?.toLowerCase() === email);
    if (user) return user;
    if (data.users.length < 200) return null;
  }
  throw new Error('Account lookup exceeded demo limit');
}

export async function handlePairing(request, { getUserClient, getAdminClient, demoSeniorId }, action = 'connect') {
  if (request.headers.get('origin') !== new URL(request.url).origin) return reply({ error: 'Use pairing controls from this dashboard.' }, 403);
  let body;
  try { body = await request.json(); }
  catch { return reply({ error: 'Invalid request body.' }, 400); }
  const email = typeof body?.email === 'string' ? body.email.trim().toLowerCase() : '';
  if (action === 'connect' && (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 254)) return reply({ error: 'Enter the senior’s account email.' }, 400);
  if (action === 'reset' && (!demoSeniorId || body?.seniorId !== demoSeniorId)) return reply({ error: 'Reset is available only for the configured demo senior.' }, 403);
  try {
    const supabase = await getUserClient();
    const { data: { user }, error: authError } = await supabase.auth.getUser();
    if (authError || !user) return reply({ error: 'Sign in to manage your connection.' }, 401);
    const own = await supabase.from('profiles').select('role').eq('id', user.id).maybeSingle();
    if (own.error) throw own.error;
    if (own.data?.role !== 'guardian') return reply({ error: 'Only a guardian can manage pairing.' }, 403);
    const admin = getAdminClient();
    let seniorId = demoSeniorId;
    if (action === 'connect') {
      const account = await findUserByEmail(admin, email);
      if (!account) return reply({ error: 'No eligible senior account found. Check the email and account setup.' }, 404);
      seniorId = account.id;
    }
    const result = await admin.from('profiles').select('id,name,role,guardian_id,consented_at').eq('id', seniorId).maybeSingle();
    if (result.error) throw result.error;
    const senior = result.data;
    if (!senior || senior.role !== 'senior') return reply({ error: 'No eligible senior account found. Check the email and account setup.' }, 404);
    if (senior.guardian_id && senior.guardian_id !== user.id) return reply({ error: 'This senior is already connected to another guardian.' }, 409);
    if (action === 'reset' && senior.guardian_id !== user.id) return reply({ error: 'This demo senior is not connected to your account.' }, 409);
    if (action === 'connect' && senior.guardian_id === user.id) return reply({ success: true, message: 'You are already connected.' });
    // Existing consent is preserved, not created by the guardian on someone else's behalf.
    if (action === 'connect' && !senior.consented_at) return reply({ error: 'This senior’s consent setup must be completed before connecting.' }, 409);
    const calls = await admin.from('calls').select('id').eq('senior_id', seniorId)
      .in('status', ['ringing', 'in_progress']).is('ended_at', null).limit(1);
    if (calls.error) throw calls.error;
    if (calls.data.length) return reply({ error: 'Finish the active call before changing pairing.' }, 409);
    const cleared = await admin.from('profiles').update({ pairing_code: null }).eq('id', user.id).eq('role', 'guardian');
    if (cleared.error) throw cleared.error;
    let change = admin.from('profiles').update({ guardian_id: action === 'reset' ? null : user.id })
      .eq('id', seniorId).eq('role', 'senior');
    // Conditional update prevents an unrelated guardian from being overwritten.
    change = action === 'reset' ? change.eq('guardian_id', user.id) : change.is('guardian_id', null);
    const updated = await change.select('id');
    if (updated.error) throw updated.error;
    if (!updated.data.length) return reply({ error: 'The connection changed. Refresh and try again.' }, 409);
    return reply({ success: true, message: action === 'reset' ? 'Demo pairing reset. The senior can stay signed in while you reconnect.' : `Connected with ${senior.name || 'your senior'}.` });
  } catch {
    return reply({ error: 'Could not update pairing. Check server configuration and try again.' }, 503);
  }
}
