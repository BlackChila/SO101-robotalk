import test from 'node:test';
import assert from 'node:assert/strict';
import { preloadRealtimeMolmo } from './realtime-molmo-preload.js';

test('a warmed model is accepted only with a hardware-free result', async () => {
  const result = await preloadRealtimeMolmo('session', async (_url, options) => {
    assert.equal(JSON.parse(options.body).sessionId, 'session');
    return { ok: true, status: 200, json: async () => ({ ready: true, hardwareCommands: false }) };
  });
  assert.deepEqual(result, { ready: true, status: 200, reason: null });
});

test('startup warmup works before a motion session exists', async () => {
  const result = await preloadRealtimeMolmo(null, async (_url, options) => {
    assert.equal(JSON.parse(options.body).sessionId, null);
    return { ok: true, status: 200, json: async () => ({ ready: true, hardwareCommands: false }) };
  });
  assert.equal(result.ready, true);
});

test('an older backend without the preload route does not abort the call', async () => {
  const result = await preloadRealtimeMolmo('session', async () => ({
    ok: false, status: 404, json: async () => ({ detail: 'Not Found' }),
  }));
  assert.deepEqual(result, { ready: false, status: 404, reason: 'Not Found' });
});

test('a warmup exception becomes a recoverable result', async () => {
  const result = await preloadRealtimeMolmo('session', async () => {
    throw new Error('Model worker unavailable');
  });
  assert.deepEqual(result, { ready: false, status: null, reason: 'Model worker unavailable' });
});
