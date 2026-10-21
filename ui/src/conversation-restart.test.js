import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
const code = source.slice(source.indexOf('async function resetConversationRobot('), source.indexOf('\nasync function startConversation('));
function harness() {
  const calls = [];
  const context = vm.createContext({
    conversationActive: true, conversationGeneration: 7, conversationMotionId: 'same-session',
    conversationVoiceOnly: false, conversationReturning: false, conversationRestartPending: false,
    conversationMode: 'realtime', activeView: 'command', conversationResetEpoch: 0,
    status: {}, renderConversationMode() {},
    realtimeTaskFeedback: { update: (...args) => calls.push(['feedback', ...args]) },
    setConversationPhase: (...args) => calls.push(['phase', ...args]),
    readJson: async r => r,
    fetch: async (url, options) => { calls.push(['fetch', url, JSON.parse(options.body)]); return { status: 'reset', controllerRestarted: true, followerTorqueHolding: true, speechGripperAvailable: true }; },
    endConversation: () => { throw Error('must keep voice connected'); },
    startConversation: () => { throw Error('must not create a new conversation'); },
  });
  vm.runInContext(code, context);
  return { context, calls };
}
test('button resets only the robot and retains session and conversation generation', async () => {
  const { context, calls } = harness();
  await context.resetConversationRobot('button-1', 'operator-reset');
  assert.equal(context.conversationActive, true);
  assert.equal(context.conversationGeneration, 7);
  assert.equal(context.conversationMotionId, 'same-session');
  assert.deepEqual(calls.find(c => c[0] === 'fetch'), ['fetch', '/api/conversation/robot/reset', { sessionId: 'same-session', callId: 'button-1' }]);
  assert.equal(context.realtimeTaskActive, false);
  assert.equal(context.conversationRestartPending, false);
});
test('failure keeps voice alive and prevents false readiness', async () => {
  const { context, calls } = harness();
  context.fetch = async () => { throw Error('hold not verified'); };
  await assert.rejects(context.resetConversationRobot('failure'), /hold not verified/);
  assert.equal(context.conversationActive, true);
  assert.ok(!calls.some(c => c[0] === 'phase' && c[1] === 'listening'));
});
test('call end during reset prevents stale readiness changes', async () => {
  const { context, calls } = harness();
  context.fetch = async () => { context.conversationActive = false; return { status: 'reset', controllerRestarted: true, followerTorqueHolding: true }; };
  await context.resetConversationRobot('old');
  assert.ok(!calls.some(c => c[0] === 'phase' && c[1] === 'listening'));
});

test('old backend reset without controller restart is not accepted as success', async () => {
  const { context } = harness();
  context.fetch = async () => ({ status: 'reset', followerTorqueHolding: true });
  await assert.rejects(context.resetConversationRobot('old-backend'), /Motorcontrollers/);
  assert.equal(context.conversationActive, true);
});
