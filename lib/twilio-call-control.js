import 'server-only';
import { stopTwilioCall } from './twilio-transport.mjs';

export async function stopCall(callSid) {
  return stopTwilioCall(callSid, {
    account: process.env.TWILIO_ACCOUNT_SID,
    token: process.env.TWILIO_AUTH_TOKEN,
  });
}
