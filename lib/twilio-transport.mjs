export async function stopTwilioCall(callSid, { account, token }) {
  if (!/^AC[0-9a-f]{32}$/i.test(account || '') || !token) {
    throw new Error('Missing Twilio call-control credentials');
  }
  const response = await fetch(
    `https://api.twilio.com/2010-04-01/Accounts/${account}/Calls/${callSid}.json`,
    {
      method: 'POST', cache: 'no-store', signal: AbortSignal.timeout(15000),
      headers: {
        Authorization: `Basic ${Buffer.from(`${account}:${token}`).toString('base64')}`,
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: new URLSearchParams({ Status: 'completed' }),
    },
  );
  if (!response.ok) throw new Error('Twilio call update failed');
  const result = await response.json();
  if (result.sid !== callSid || result.status !== 'completed') {
    throw new Error('Twilio did not confirm call completion');
  }
}
