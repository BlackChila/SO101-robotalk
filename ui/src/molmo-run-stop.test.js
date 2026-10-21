import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { molmoRunStopState, keepMolmoForConversation } from './molmo-run-stop.js';

test('run stop is enabled only for an active task and uses the requested label', () => {
  for (const state of ['loading', 'running']) {
    const control = molmoRunStopState({ model: 'molmoact2', state });
    assert.equal(control.disabled, false);
    assert.equal(control.label, 'Model Run stoppen');
  }
  for (const task of [null, { model: 'molmoact2', state: 'stopped' },
    { model: 'molmoact2', state: 'stopping' }, { model: 'g05', state: 'running' }]) {
    assert.equal(molmoRunStopState(task).disabled, true);
  }
  assert.equal(molmoRunStopState({ model: 'molmoact2', state: 'running' }, true).disabled, true);
});

test('restored operator stop preserves the model, voice and camera session', async () => {
  const main = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const handler = main.slice(main.indexOf('async function stopConversationTask('),
    main.indexOf('async function stopLocalConversationTask('));
  for (const conversationActive of [true, false]) {
    const requests = [];
    const context = vm.createContext({
      status: { modelSession: 'molmoact2', cameraModel: 'molmoact2', taskRun: { model: 'molmoact2', state: 'running' } },
      conversationActive, conversationTaskStopPending: false, conversationTaskFeedback: {},
      molmoRunStopState, renderConversationTaskStop() {}, refreshStatus: async () => {},
      readJson: async response => response,
      fetch: async (url, options) => {
        requests.push({ url, method: options.method, operator: options.headers['X-SO101-Stop'] });
        return { taskRun: { model: 'molmoact2', state: 'stopping' } };
      },
      endConversation() { throw Error('Must keep voice'); },
    });
    vm.runInContext(handler, context);
    await context.stopConversationTask();
    assert.deepEqual(requests, [{ url: '/api/task/stop', method: 'POST', operator: 'operator-click' }]);
    assert.equal(context.status.modelSession, 'molmoact2');
    assert.equal(context.status.cameraModel, 'molmoact2');
    assert.equal(context.conversationActive, conversationActive);
    assert.equal(context.conversationTaskStopPending, false);
    await context.stopConversationTask();
    assert.equal(requests.length, 1, 'stopping tasks cannot issue another stop');
  }
});

test('local cancellation does not delay the physical stop', async () => {
  const main = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const code = main.slice(main.indexOf('async function stopLocalConversationTask('),
    main.indexOf("conversationTaskStop.addEventListener('click'"));
  let finishCancellation;
  let stopped = false;
  let listened = false;
  const context = vm.createContext({
    status: { taskRun: { model: 'molmoact2', state: 'running' } },
    conversationTaskStopPending: false, conversationGeneration: 1, conversationActive: true,
    conversationRestartPending: false, conversationTaskFeedback: {}, conversationRequest: null,
    molmoRunStopState, stopConversationRecording() {},
    localConversation: { cancelTurn: () => new Promise(resolve => { finishCancellation = resolve; }) },
    stopConversationTask: async () => { stopped = true; },
    listenForConversation: () => { listened = true; },
  });
  vm.runInContext(code, context);
  const pending = context.stopLocalConversationTask();
  assert.equal(stopped, true);
  assert.equal(listened, false);
  finishCancellation();
  await pending;
  assert.equal(listened, true);
});

test('entering realtime retains warm Molmo and an in-flight Molmo task', () => {
  assert.equal(keepMolmoForConversation('realtime', { modelSession: 'molmoact2' }), true);
  assert.equal(keepMolmoForConversation('realtime', { taskRun: { model: 'molmoact2', state: 'running' } }), true);
  assert.equal(keepMolmoForConversation('local', { modelSession: 'molmoact2' }), true);
  assert.equal(keepMolmoForConversation('realtime', { modelSession: 'g05' }), false);
});

test('homepage initialization reads fresh backend state before considering an unload', async () => {
  const main = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const start = main.indexOf('async function initializeConversation(');
  const end = main.indexOf("void initializeConversation();", start);
  const calls = [];
  const context = vm.createContext({
    status: { modelSession: null }, conversationMode: 'realtime', activeView: 'conversation',
    conversationActive: false, conversationReturning: false, conversationEntryReady: false,
    conversationEntryPending: false, phase: 'idle', conversationCall: {}, cameraGeneration: 0,
    cameraReady: false, keepMolmoForConversation, AbortController, setTimeout, clearTimeout,
    displayView() {}, setConversationPhase() {}, renderConversationMode() {}, render() {},
    refreshConversationStatus: async () => {}, prepareConversation: async () => {},
    ensureConversationCameras: async () => {
      assert.equal(context.status.cameraModel, 'molmoact2');
    },
    releaseModelSession: async () => { throw Error('Must not unload warm Molmo'); },
    readJson: async value => value,
    fetch: async url => {
      calls.push(url);
      return url === '/api/status' ? { modelSession: 'molmoact2', cameraModel: 'molmoact2' }
        : url.includes('/motion/') ? { occupied: false } : { followerPortAvailable: true };
    },
  });
  vm.runInContext(main.slice(start, end), context);
  await context.initializeConversation();
  assert.equal(calls[0], '/api/status');
  assert.equal(context.status.modelSession, 'molmoact2');
  assert.equal(context.conversationEntryReady, true);
});

test('Piper entry retains a warm Molmo model without retaining other policies', () => {
  assert.equal(keepMolmoForConversation('piper', { modelSession: 'molmoact2' }), true);
  assert.equal(keepMolmoForConversation('piper', { modelSession: 'g05' }), false);
});
