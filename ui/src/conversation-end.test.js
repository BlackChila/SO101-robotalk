import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
const normalEnd = source.slice(source.indexOf('function endConversation('), source.indexOf("\nconversationCall.addEventListener", source.indexOf('function endConversation(')));
const recoveredEnd = source.slice(source.indexOf('async function endRecoveredConversation('), source.indexOf('\nasync function releaseModelSession('));
const stopMotion = source.slice(source.indexOf('async function stopConversationMotion('), source.indexOf('\nasync function waitForConversationIntro('));
function harness({ activeTask = false, recovered = false, state = null } = {}) {
  const calls = [];
  const sessionId = 'a'.repeat(32);
  const motion = { sessionId, state: state || (recovered ? 'stopped' : 'holding'), occupied: true,
    active: !recovered, taskWasStarted: true, followerTorqueHolding: true };
  const context = vm.createContext({
    conversationActive: !recovered, conversationStopping: Promise.resolve(), conversationGeneration: 1,
    conversationRequest: null, conversationAudio: null, conversationStream: null, conversationAudioContext: null,
    conversationAnalyser: null, conversationHeartbeat: null, conversationVoiceOnly: false,
    conversationMotionId: recovered ? null : sessionId, conversationRecoveredId: recovered ? sessionId : null,
    realtimeTaskEverStarted: true, realtimeTaskActive: activeTask,
    conversationReturning: false, conversationReturnCancel: null,
    conversationCall: { disabled: false }, conversationFeedback: { textContent: '' },
    clearInterval() {}, setTimeout() {}, stopConversationRecording() {}, stopRealtimeSession() {},
    renderConversationTaskStop() {}, refreshConversationStatus() {},
    faceTracking: { command: async action => { calls.push(['face-tracking', action]); } },
    sessionStorage: { removeItem() {} },
    setConversationPhase(phase, text) { calls.push(['phase', phase, text]); },
    readJson: async response => response.body,
    fetch: async url => {
      calls.push(['fetch', url]);
      return { ok: true, body: url === '/api/task/status' ? { taskRun: { state: 'stopped' } } : motion };
    },
    postConversationMotion: async path => { calls.push(['motion', path]); return {}; },
    waitForConversationReturn: async () => { calls.push(['wait-return']); return true; },
    stopConversationMotion: async returnToStart => {
      calls.push(['stop-motion', returnToStart]); context.conversationMotionId = null;
      return { returnedToStart: returnToStart };
    },
  });
  vm.runInContext(normalEnd + '\n' + recoveredEnd, context);
  return { calls, context };
}

test('operator end returns to the intro start after a previous robot task', async () => {
  const h = harness();
  await h.context.endConversation();
  assert.deepEqual(h.calls.filter(c => c[0] === 'motion' || c[0] === 'stop-motion'),
    [['motion', 'return'], ['stop-motion', true]]);
});

test('operator end waits for an active task to stop before returning', async () => {
  const h = harness({ activeTask: true });
  await h.context.endConversation();
  const stop = h.calls.findIndex(c => c[1] === '/api/task/stop');
  const held = h.calls.findIndex(c => c[1] === '/api/task/status');
  const returning = h.calls.findIndex(c => c[0] === 'motion' && c[1] === 'return');
  assert.ok(stop >= 0 && held > stop && returning > held);
  assert.equal(h.context.realtimeTaskActive, false);
});

test('error-driven shutdown holds in place without requesting return', async () => {
  const h = harness();
  await h.context.endConversation(true);
  assert.deepEqual(h.calls.filter(c => c[0] === 'motion' || c[0] === 'stop-motion'),
    [['stop-motion', false]]);
});

test('operator end of a recovered stopped task session requests the return leg', async () => {
  const h = harness({ recovered: true });
  await h.context.endRecoveredConversation();
  assert.deepEqual(h.calls.filter(c => c[0] === 'motion' || c[0] === 'stop-motion'),
    [['motion', 'return-stopped'], ['stop-motion', true]]);
});


test('conversation end stops gaze before the return or task stop handover', async () => {
  const h = harness({ activeTask: true });
  await h.context.endConversation();
  const gaze = h.calls.findIndex(c => c[0] === 'face-tracking' && c[1] === 'stop');
  const task = h.calls.findIndex(c => c[1] === '/api/task/stop');
  assert.ok(gaze >= 0 && task > gaze);
});

for (const state of ['starting', 'positioning', 'intro']) {
  test(`operator end during ${state} requests return instead of silently holding in place`, async () => {
    const h = harness({ state });
    await h.context.endConversation();
    assert.deepEqual(h.calls.filter(c => c[0] === 'motion' || c[0] === 'stop-motion'),
      [['motion', 'return'], ['stop-motion', true]]);
  });
}

test('controller task state triggers task stop even when the UI flag is stale', async () => {
  const h = harness({ state: 'task' });
  await h.context.endConversation();
  const stopped = h.calls.findIndex(c => c[1] === '/api/task/stop');
  const returning = h.calls.findIndex(c => c[0] === 'motion' && c[1] === 'return');
  assert.ok(stopped >= 0 && returning > stopped);
});

test('failed hold frees an exited conversation session for a fresh start', async () => {
  const sessionId = 'a'.repeat(32);
  const storage = new Map([['so101-conversation-motion-id', sessionId]]);
  const context = vm.createContext({
    conversationHeartbeat: null, conversationMotionId: sessionId,
    clearInterval() {},
    sessionStorage: {
      getItem: key => storage.get(key) || null,
      removeItem: key => storage.delete(key),
    },
    postConversationMotion: async () => { throw new Error('Follower hold unverified'); },
    fetch: async () => ({ body: { sessionId, active: false, state: 'failed' } }),
    readJson: async response => response.body,
  });
  vm.runInContext(stopMotion, context);
  await assert.rejects(context.stopConversationMotion(), /Follower hold unverified/);
  assert.equal(context.conversationMotionId, null);
  assert.equal(storage.has('so101-conversation-motion-id'), false);
});

for (const mode of ['realtime', 'piper', 'local']) {
  for (const recovered of [false, true]) {
    test(`${mode}: ${recovered ? 'recovered' : 'active'} interrupted return closes after verified hold`, async () => {
      const h = harness({ recovered });
      h.context.conversationMode = mode;
      h.context.waitForConversationReturn = async () => { throw Error('KeyboardInterrupt: SIGTERM'); };
      h.context.stopConversationMotion = async () => {
        h.context.conversationMotionId = null;
        return { followerTorqueHolding: true, returnedToStart: false };
      };
      await (recovered ? h.context.endRecoveredConversation() : h.context.endConversation());
      assert.equal(h.context.conversationCall.disabled, false);
      assert.equal(h.context.conversationRecoveredId, null);
      assert.ok(h.calls.some(c => c[0] === 'phase' && c[1] === 'idle' && c[2].includes('Rückfahrt unterbrochen')));
      assert.ok(!h.calls.some(c => c[0] === 'phase' && c[1] === 'error'));
    });
  }
}

test('cleanup failure remains visible instead of dismissing the return error', async () => {
  const h = harness();
  h.context.waitForConversationReturn = async () => { throw Error('KeyboardInterrupt: SIGTERM'); };
  h.context.stopConversationMotion = async () => { throw Error('Follower hold unverified'); };
  await h.context.endConversation();
  assert.equal(h.context.conversationCall.disabled, true);
  assert.ok(h.calls.some(c => c[0] === 'phase' && c[1] === 'error' && c[2].includes('Follower hold unverified')));
});
