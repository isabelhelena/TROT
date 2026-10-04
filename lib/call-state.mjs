export const isActive = (call) => ['ringing', 'in_progress'].includes(call?.status);
export const isDemo = (call) => call?.call_sid?.startsWith('DEMO_');
export function mergeRow(rows, row) {
  return [...rows.filter((item) => item.id !== row.id), row]
    .sort((a, b) => (a.started_at || a.created_at || '').localeCompare(b.started_at || b.created_at || '') || a.id.localeCompare(b.id));
}
export function currentCall(calls) {
  return [...calls].filter(isActive).sort((a, b) => b.started_at.localeCompare(a.started_at))[0] || null;
}
export function hasWarning(call, alerts) {
  return isActive(call) && (call.risk === 'scam' || alerts.some((alert) => alert.call_sid === call.call_sid));
}
