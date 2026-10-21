import test from 'node:test';
import assert from 'node:assert/strict';
import { waitForRealtimeChannel } from './realtime-connection.js';

function connecting() {
  return [Object.assign(new EventTarget(), { readyState: 'connecting' }),
    Object.assign(new EventTarget(), { connectionState: 'connecting' })];
}

test('waits until the data channel opens', async () => {
  const [channel, peer] = connecting();
  const ready = waitForRealtimeChannel(channel, peer);
  channel.readyState = 'open';
  channel.dispatchEvent(new Event('open'));
  await ready;
  await waitForRealtimeChannel(channel, peer);
});

test('a connection that never opens reports a timeout', async () => {
  const [channel, peer] = connecting();
  await assert.rejects(waitForRealtimeChannel(channel, peer, 5), /Zeitlimit/);
});

test('a failed peer reports failure without waiting for the timeout', async () => {
  const [channel, peer] = connecting();
  const ready = waitForRealtimeChannel(channel, peer);
  peer.connectionState = 'failed';
  peer.dispatchEvent(new Event('connectionstatechange'));
  await assert.rejects(ready, /nicht geöffnet/);
});
