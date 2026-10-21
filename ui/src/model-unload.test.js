import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
const start = source.indexOf('function setModelUnloadFeedback(');
const end = source.indexOf("modelUnload.addEventListener('click'", start);

function harness(view = 'conversation') {
  const requests = [];
  const context = vm.createContext({
    activeView: view, phase: 'idle', conversationEntryPending: false,
    conversationReturning: false, conversationRestartPending: false,
    conversationActive: true, modelManuallyUnloaded: false,
    status: { modelSession: 'molmoact2', cameraModel: 'molmoact2' },
    conversationTaskFeedback: { hidden: true },
    render() {}, setFeedback() {}, refreshStatus: async () => {},
    sessionStorage: { setItem() {} }, readJson: async value => value,
    fetch: async (url, options) => { requests.push([url, options.method]); return {}; },
    endConversation() { throw Error('Do not end voice'); },
    stopConversationMotion() { throw Error('Do not alter the motor holder'); },
  });
  vm.runInContext(source.slice(start, end), context);
  return { context, requests };
}

test('conversation settings unload only the policy while preserving cameras and conversation', async () => {
  for (const view of ['conversation']) {
    const { context, requests } = harness(view);
    await context.unloadModel();
    assert.deepEqual(requests, [['/api/models/current', 'DELETE']]);
    assert.equal(context.status.modelSession, null);
    assert.equal(context.status.cameraModel, 'molmoact2');
    assert.equal(context.conversationActive, true);
    assert.equal(context.modelManuallyUnloaded, true);
    assert.equal(context.phase, 'idle');
    if (view === 'conversation') {
      assert.equal(context.conversationTaskFeedback.hidden, false);
      assert.match(context.conversationTaskFeedback.textContent, /Modell entladen/);
    }
  }
});

test('busy lifecycle and active runs block unload without sending a request', async () => {
  for (const overrides of [
    ...['loading', 'running', 'stopping'].map(state => ({ status: { modelSession: 'molmoact2', taskRun: { state } } })),
    { status: { modelSession: null } }, { status: { modelSession: 'molmoact2', resetRunning: true } },
    { phase: 'unloading' }, { conversationEntryPending: true },
    { conversationReturning: true }, { conversationRestartPending: true },
  ]) {
    const { context, requests } = harness();
    Object.assign(context, overrides);
    await context.unloadModel();
    assert.deepEqual(requests, []);
  }
});

test('failed unload retains loaded state and reports the error in conversation', async () => {
  const { context } = harness();
  context.fetch = async () => { throw Error('Worker belegt'); };
  await context.unloadModel();
  assert.equal(context.status.modelSession, 'molmoact2');
  assert.equal(context.modelManuallyUnloaded, false);
  assert.equal(context.phase, 'idle');
  assert.match(context.conversationTaskFeedback.textContent, /Worker belegt/);
});
