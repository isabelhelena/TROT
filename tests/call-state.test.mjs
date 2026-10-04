import test from 'node:test';
import assert from 'node:assert/strict';
import { currentCall, hasWarning, mergeRow, isDemo } from '../lib/call-state.mjs';
const old = { id: 'old', call_sid: 'DEMO_old', status: 'completed', risk: 'scam', started_at: '2026-01-01' };
const live = { id: 'live', call_sid: 'CA_live', status: 'ringing', risk: 'none', started_at: '2026-01-02' };
test('only the active call controls senior warnings', () => {
  assert.equal(currentCall([old, live]), live);
  assert.equal(hasWarning(live, [{call_sid: old.call_sid}]), false);
  assert.equal(hasWarning(live, [{call_sid: live.call_sid}]), true);
  assert.equal(hasWarning(old, [{call_sid: old.call_sid}]), false);
  assert.equal(currentCall([old, {...live, status: 'completed'}]), null);
});
test('replayed rows replace duplicates and preserve timeline order', () => {
  const rows = mergeRow([live, old], {...live, status: 'in_progress'});
  assert.equal(rows.length, 2);
  assert.equal(rows[1].status, 'in_progress');
  assert.equal(isDemo(old), true);
  assert.equal(isDemo(live), false);
});
