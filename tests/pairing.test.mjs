import test from 'node:test';
import assert from 'node:assert/strict';
import { handlePairing } from '../lib/pairing.mjs';

function fixture({ role = 'guardian', signedIn = true, linked = null, consent = true, active = false, missing = false, race = false } = {}) {
  const profiles = [
    { id: 'guardian', role, pairing_code: 'old-code' },
    { id: 'senior', role: 'senior', name: 'Demo senior', guardian_id: linked,
      consented_at: consent ? '2026-01-01' : null, phone: '+15555550102', twilio_number: '+15555550103' },
  ];
  const calls = active ? [{ id: 'call', senior_id: 'senior', status: 'in_progress', ended_at: null }] : [];
  const writes = [];
  function from(table) {
    const filters = [];
    let values, single = false;
    const query = {
      select() { return query; },
      limit() { return query; },
      eq(key, value) { filters.push((row) => row[key] === value); return query; },
      is(key, value) { filters.push((row) => (row[key] ?? null) === value); return query; },
      in(key, options) { filters.push((row) => options.includes(row[key])); return query; },
      update(data) { values = data; return query; },
      maybeSingle() { single = true; return query; },
      then(resolve, reject) {
        if (race && table === 'profiles' && values?.guardian_id === 'guardian') profiles[1].guardian_id = 'someone-else';
        const rows = (table === 'profiles' ? profiles : calls).filter((row) => filters.every((filter) => filter(row)));
        if (values) { writes.push({ table, values }); rows.forEach((row) => Object.assign(row, values)); }
        return Promise.resolve({ data: single ? rows[0] ? { ...rows[0] } : null : rows.map((row) => ({ ...row })) }).then(resolve, reject);
      },
    };
    return query;
  }
  const admin = { from, auth: { admin: { listUsers: async () => ({data: {users: missing ? [] : [{id:'senior',email:'senior@example.com'}]}}) } } };
  const user = { from, auth: { getUser: async () => ({data: {user: signedIn ? {id:'guardian'} : null}}) } };
  return { profiles, calls, writes, dependencies: { getUserClient: async () => user, getAdminClient: () => admin, demoSeniorId: 'senior' } };
}
function request(body = {email:' SENIOR@example.com '}, origin = 'http://localhost:3000') {
  return new Request('http://localhost:3000/api/pair', {method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:JSON.stringify(body)});
}

test('guardian connects by normalized email and preserves phone/consent setup', async () => {
  const f = fixture();
  const original = {...f.profiles[1]};
  assert.equal((await handlePairing(request(),f.dependencies)).status,200);
  assert.deepEqual(f.profiles[1],{...original,guardian_id:'guardian'});
  assert.equal(f.profiles[0].pairing_code,null);
});

test('pairing reset and reconnect is repeatable without changing history or setup', async () => {
  const f = fixture({linked:'guardian'});
  assert.equal((await handlePairing(request({seniorId:'senior'}),f.dependencies,'reset')).status,200);
  assert.equal(f.profiles[1].guardian_id,null);
  assert.equal((await handlePairing(request(),f.dependencies)).status,200);
  assert.equal(f.profiles[1].guardian_id,'guardian');
  assert.equal(f.profiles[1].phone,'+15555550102');
  assert.equal(f.profiles[1].consented_at,'2026-01-01');
  assert.equal(f.calls.length,0);
});

test('authentication, guardian role, and origin are required', async () => {
  for (const [options,status] of [[{signedIn:false},401],[{role:'senior'},403]]) {
    const f=fixture(options);
    assert.equal((await handlePairing(request(),f.dependencies)).status,status);
    assert.equal(f.writes.length,0);
  }
  const f=fixture();
  assert.equal((await handlePairing(request({},'https://other.example'),f.dependencies)).status,403);
  assert.equal(f.writes.length,0);
});

test('existing links are retained and someone else’s senior cannot be taken over', async () => {
  const own=fixture({linked:'guardian'});
  assert.equal((await handlePairing(request(),own.dependencies)).status,200);
  assert.equal(own.writes.length,0);
  const other=fixture({linked:'other'});
  assert.equal((await handlePairing(request(),other.dependencies)).status,409);
  assert.equal(other.writes.length,0);
});

test('reset is restricted to the configured demo senior and owning guardian', async () => {
  const f=fixture({linked:'guardian'});
  assert.equal((await handlePairing(request({seniorId:'other'}),f.dependencies,'reset')).status,403);
  const other=fixture({linked:'other'});
  assert.equal((await handlePairing(request({seniorId:'senior'}),other.dependencies,'reset')).status,409);
  assert.equal(f.writes.length,0);
  assert.equal(other.writes.length,0);
});

test('active calls prevent both connecting and reset', async () => {
  const f=fixture({active:true});
  assert.equal((await handlePairing(request(),f.dependencies)).status,409);
  const paired=fixture({active:true,linked:'guardian'});
  assert.equal((await handlePairing(request({seniorId:'senior'}),paired.dependencies,'reset')).status,409);
  assert.equal(f.writes.length,0);
  assert.equal(paired.writes.length,0);
});

test('missing account and missing consent do not create a connection', async () => {
  for (const [options,status] of [[{missing:true},404],[{consent:false},409]]) {
    const f=fixture(options);
    assert.equal((await handlePairing(request(),f.dependencies)).status,status);
    assert.equal(f.writes.length,0);
  }
});

test('conditional update does not overwrite a concurrent connection', async () => {
  const f=fixture({race:true});
  assert.equal((await handlePairing(request(),f.dependencies)).status,409);
  assert.equal(f.profiles[1].guardian_id,'someone-else');
});
