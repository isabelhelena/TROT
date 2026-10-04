import test from 'node:test';
import assert from 'node:assert/strict';
import { handleEndCall } from '../lib/end-call.mjs';
import { stopTwilioCall } from '../lib/twilio-transport.mjs';
const stopCall = (sid) => stopTwilioCall(sid, { account: process.env.TWILIO_ACCOUNT_SID, token: process.env.TWILIO_AUTH_TOKEN });

const sid = 'CA' + 'a'.repeat(32);
function fixture({ role = 'guardian', owner = 'guardian', status = 'in_progress', user = true, failTwilio = false, failSync = false } = {}) {
  const call = { id: 'call-id', call_sid: sid, guardian_id: owner, status, ended_at: null };
  const writes = [], stops = [];
  function client(admin = false) {
    return {
      auth: { getUser: async () => ({ data: { user: user ? { id: 'guardian' } : null } }) },
      from(table) {
        const filters = [];
        let values;
        const query = {
          select() { return query; },
          eq(key, value) { filters.push((row) => row[key] === value); return query; },
          in(key, options) { filters.push((row) => options.includes(row[key])); return query; },
          update(data) { values = data; return query; },
          async maybeSingle() {
            const row = table === 'profiles' ? { id: 'guardian', role } : call;
            return { data: filters.every((filter) => filter(row)) ? { ...row } : null };
          },
          then(resolve, reject) {
            if (values && failSync) return Promise.resolve({ error: new Error('sync failure') }).then(resolve, reject);
            const matches = filters.every((filter) => filter(call));
            if (values && matches && admin) { writes.push(values); Object.assign(call, values); }
            return Promise.resolve({ data: matches ? [{ id: call.id }] : [] }).then(resolve, reject);
          },
        };
        return query;
      },
    };
  }
  return { call, writes, stops, dependencies: {
    getUserClient: async () => client(), getAdminClient: () => client(true),
    stopCall: async (value) => { stops.push(value); if (failTwilio) throw new Error('Twilio failed'); },
  } };
}
function request(callSid = sid, origin = 'http://localhost:3000') {
  return new Request('http://localhost:3000/api/calls/end', {
    method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json' },
    body: JSON.stringify({ callSid }),
  });
}

test('hangup verifies ownership, disconnects, then finishes the record', async () => {
  const f = fixture();
  const response = await handleEndCall(request(), f.dependencies);
  assert.equal(response.status, 200);
  assert.deepEqual(f.stops, [sid]);
  assert.equal(f.call.status, 'completed');
  assert.ok(f.call.ended_at);
  assert.equal((await response.json()).synced, true);
});

test('unauthenticated, senior, other guardian, and ended calls cannot hang up', async () => {
  for (const [options, status] of [[{user:false},401], [{role:'senior'},403], [{owner:'other'},404], [{status:'completed'},409]]) {
    const f = fixture(options);
    assert.equal((await handleEndCall(request(), f.dependencies)).status, status);
    assert.equal(f.stops.length, 0);
    assert.equal(f.writes.length, 0);
  }
});

test('cross-origin and simulated/invalid SIDs never reach Twilio', async () => {
  const f = fixture();
  assert.equal((await handleEndCall(request(sid, 'https://other.example'), f.dependencies)).status, 403);
  assert.equal((await handleEndCall(request('DEMO_example'), f.dependencies)).status, 400);
  assert.equal(f.stops.length, 0);
});

test('failed Twilio request never marks the call completed', async () => {
  const f = fixture({failTwilio:true});
  assert.equal((await handleEndCall(request(), f.dependencies)).status, 502);
  assert.equal(f.call.status, 'in_progress');
  assert.equal(f.writes.length, 0);
});

test('hangup success with failed database sync is reported accurately', async () => {
  const f = fixture({failSync:true});
  const response = await handleEndCall(request(), f.dependencies);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).synced, false);
  assert.equal(f.stops.length, 1);
});

test('Twilio transport posts completed to the specified call, without live requests', async () => {
  const previous = { fetch: globalThis.fetch, account: process.env.TWILIO_ACCOUNT_SID, token: process.env.TWILIO_AUTH_TOKEN };
  process.env.TWILIO_ACCOUNT_SID = 'AC' + 'b'.repeat(32);
  process.env.TWILIO_AUTH_TOKEN = 'test-token';
  try {
    globalThis.fetch = async (url, options) => {
      assert.ok(url.endsWith(`/Calls/${sid}.json`));
      assert.equal(options.method, 'POST');
      assert.equal(options.body.toString(), 'Status=completed');
      assert.equal(Buffer.from(options.headers.Authorization.slice(6), 'base64').toString(), `${process.env.TWILIO_ACCOUNT_SID}:test-token`);
      return Response.json({ sid, status: 'completed' });
    };
    await stopCall(sid);
    globalThis.fetch = async () => new Response('', {status:403});
    await assert.rejects(stopCall(sid));
  } finally {
    globalThis.fetch = previous.fetch;
    for (const [key, value] of [['TWILIO_ACCOUNT_SID',previous.account], ['TWILIO_AUTH_TOKEN',previous.token]]) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
});
