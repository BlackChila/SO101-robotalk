import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { FaceTrackingControls } from './face-tracking.js';

const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
const extract = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));
const functions = extract('function currentCameraModel()', '\nfunction renderConversationSettings()')
  + extract('async function ensureConversationCameras()', '\nasync function pollCameraPreview()')
  + extract('async function applyCameraBrightness(', '\nasync function applyCameraExposure(');

function harness() {
  const calls = [];
  const control = { role: 'cam0', receive(value, role, applied) { calls.push(['receive', value, role, applied]); } };
  const context = vm.createContext({
    activeView: 'conversation', status: { cameraModel: 'molmoact2' },
    conversationSettings: { open: true }, conversationEntryPending: false, phase: 'idle', cameraOpening: false,
    cameraReady: false, cameraPreviewModelId: 'molmoact2', cameraGeneration: 0,
    cameraFrameReady: [true, true], wristObserverReady: true,
    cameraStatus: {}, conversationCameraStatus: {}, brightnessControls: [control],
    fetch: async (url, options) => {
      calls.push(['fetch', url, options]);
      return { body: { cameraBrightness: { cam0: { value: 12 } } } };
    },
    readJson: async response => response.body,
    showCameraFrames: (payload, model) => calls.push(['show', model]),
    render() {}, refreshStatus: async () => {},
    setFeedback: (...args) => calls.push(['feedback', ...args]),
  });
  vm.runInContext(functions, context);
  return { context, calls };
}

test('Gespräch reads the active camera profile', async () => {
  const h = harness();
  await h.context.refreshVisibleCameraPreview();
  assert.equal(h.calls[0][1], '/api/cameras/molmoact2/preview');
  assert.equal(h.calls[1][1], 'molmoact2');
  assert.equal(h.context.cameraReady, true);
  assert.ok(h.calls.every(call => call[0] !== 'fetch' || !call[1].endsWith('/select')));
});

test('closed Gespräch settings still refresh camera readiness and start cameras without a model', async () => {
  const h = harness();
  h.context.conversationSettings.open = false;
  await h.context.refreshVisibleCameraPreview();
  assert.equal(h.calls[0][1], '/api/cameras/molmoact2/preview');
  assert.equal(h.context.cameraReady, true);
  h.calls.length = 0;
  h.context.status.cameraModel = null;
  h.context.status.modelSession = null;
  await h.context.refreshVisibleCameraPreview();
  assert.equal(h.calls[0][1], '/api/cameras/conversation/select');
  assert.equal(h.context.status.modelSession, null);
  assert.equal(h.context.status.cameraModel, 'conversation');
  assert.equal(h.context.cameraReady, true);
  assert.ok(h.calls.every(call => call[0] !== 'fetch' || !call[1].startsWith('/api/models/')));
});

test('retained Molmo cameras enable tracking after intro with settings closed', async () => {
  const h = harness();
  h.context.conversationSettings.open = false;
  h.context.conversationEntryPending = true;
  const trackingCalls = [];
  const control = new FaceTrackingControls({ querySelector: () => ({ removeAttribute() {} }) }, {
    storage: null, setTimer: () => 1, clearTimer() {},
    fetchImpl: async (_, options) => {
      trackingCalls.push(JSON.parse(options.body));
      return { ok: true, json: async () => ({ mode: 'tracking' }) };
    },
  });
  let introComplete = false;
  h.context.render = () => control.setContext({
    view: 'conversation', mode: 'realtime', cameraReady: h.context.cameraReady,
    connected: true, active: true, sessionId: 'new-call', introComplete,
  });
  await h.context.ensureConversationCameras();
  await control.queue;
  assert.equal(h.context.cameraReady, true);
  assert.deepEqual(trackingCalls, []);
  introComplete = true;
  h.context.render();
  await control.queue;
  assert.equal(trackingCalls.length, 1);
  assert.equal(trackingCalls[0].action, 'enable');
  assert.equal(trackingCalls[0].sessionId, 'new-call');
  assert.equal(h.context.conversationSettings.open, false);
  assert.ok(h.calls.every(c => c[0] !== 'fetch' || !c[1].endsWith('/select')));
});

test('holding intro automatically starts Realtime tracking with Gespräch settings closed', async () => {
  const actions = [];
  const control = new FaceTrackingControls({ querySelector: () => ({ removeAttribute() {} }) }, {
    storage: null, setTimer: () => 1, clearTimer() {},
    fetchImpl: async (_, options) => {
      actions.push(JSON.parse(options.body));
      return { ok: true, json: async () => ({ mode: 'tracking' }) };
    },
  });
  const context = vm.createContext({
    conversationActive: true, conversationGeneration: 1, conversationMotionId: 'new-call',
    conversationIntroCompletedId: null, conversationSettings: { open: false },
    fetch: async () => ({ body: { sessionId: 'new-call', state: 'holding' } }),
    readJson: async response => response.body,
  });
  context.render = () => control.setContext({
    view: 'conversation', mode: 'realtime', cameraReady: true,
    settingsOpen: context.conversationSettings.open, connected: true, active: context.conversationActive,
    sessionId: context.conversationMotionId,
    introComplete: context.conversationIntroCompletedId === context.conversationMotionId,
  });
  vm.runInContext(extract('async function waitForConversationIntro(', '\nasync function waitForConversationReturn('), context);
  context.render();
  await control.queue;
  assert.deepEqual(actions, []);
  await context.waitForConversationIntro(1, { quiet: true });
  await control.queue;
  assert.equal(context.conversationIntroCompletedId, 'new-call');
  assert.equal(context.conversationSettings.open, false);
  assert.deepEqual(actions.map(action => action.action), ['enable']);
  assert.equal(actions[0].sessionId, 'new-call');
});

test('brightness updates target the displayed camera and actual source', async () => {
  const h = harness();
  await h.context.applyCameraBrightness('cam0', 12, { apply: { disabled: false }, message: {} });
  assert.equal(h.calls[0][1], '/api/cameras/molmoact2/cam0/brightness');
  assert.equal(h.calls[0][2].method, 'POST');
  assert.deepEqual(JSON.parse(h.calls[0][2].body), { value: 12 });
  assert.equal(h.context.cameraOpening, false);
  assert.ok(h.calls.some(call => call[0] === 'receive' && call[3] === true));
});

test('a preview returned after a profile switch cannot replace the current images', async () => {
  const h = harness();
  let finish;
  h.context.fetch = () => new Promise(resolve => { finish = resolve; });
  const pending = h.context.refreshVisibleCameraPreview();
  h.context.status.cameraModel = 'conversation';
  finish({ body: {} });
  await pending;
  assert.deepEqual(h.calls, []);
  assert.equal(h.context.cameraReady, false);
});

test('an idle conversation permits camera adjustment; loading, running, stopping and return keep it locked', () => {
  const render = source.indexOf('function render() {');
  const conditions = source.slice(source.indexOf('  const taskRunning =', render), source.indexOf('  cameraSettings.forEach', render));
  for (const state of [null, 'loading', 'running', 'stopping', 'returning']) {
    const h = harness();
    Object.assign(h.context, {
      cameraReady: true, liveCameraPanel: {}, backendReady: true,
      conversationEntryPending: false, conversationMotionId: 'active-conversation',
      conversationReturning: state === 'returning',
    });
    h.context.status.taskRun = state && state !== 'returning' ? { state } : null;
    vm.runInContext(conditions, h.context);
    assert.equal(vm.runInContext('cameraSettingsBusy', h.context), state !== null);
  }
});


test('optional wrist preview has independent controls and disappears outside MolmoAct2', () => {
  const received = [];
  const trackingPreview = { hidden: true };
  const image = { src: null, removeAttribute() { this.src = null; } };
  const control = kind => ({ receive(value, role) { received.push([kind, value, role]); } });
  const context = vm.createContext({
    activeView: 'conversation', cameraFrameReady: [true, true], wristObserverReady: false, wristObserverFigure: { hidden: true },
    cameraViews: { classList: { toggle(name, enabled) { received.push([name, enabled]); } } },
    cameraImages: [{ closest: () => ({}) }, { closest: () => ({}) }, image], brightnessControls: [{}, {}, control('brightness')],
    exposureControls: [{}, {}, control('exposure')],
    document: { querySelector: () => trackingPreview },
  });
  vm.runInContext(extract('function showWristObserver(', '\nasync function applyCameraBrightness('), context);
  const payload = { observerPreviews: { wrist: { jpeg: 'wrist-frame' } },
    cameraBrightness: { wrist: { value: -32 } }, cameraExposure: { wrist: { value: 50 } } };
  context.showWristObserver(payload, 'molmoact2');
  assert.equal(context.wristObserverFigure.hidden, false);
  assert.equal(image.src, 'data:image/jpeg;base64,wrist-frame');
  assert.deepEqual(received.find(call => call[0] === 'brightness'), ['brightness', payload.cameraBrightness.wrist, 'wrist']);
  context.activeView = 'command';
  context.renderWristObserver();
  assert.equal(context.wristObserverFigure.hidden, true);
  assert.deepEqual(received.filter(call => call[0] === 'camera-views--three').at(-1), ['camera-views--three', false]);
  context.showWristObserver(payload, 'molmoact2');
  assert.equal(context.wristObserverFigure.hidden, true);
  context.activeView = 'conversation';
  context.renderWristObserver();
  assert.equal(context.wristObserverFigure.hidden, false);
  context.showWristObserver({}, 'molmoact2');
  assert.equal(context.wristObserverFigure.hidden, true);
  assert.equal(image.src, null);
  context.showWristObserver(payload, 'g05');
  assert.equal(context.wristObserverFigure.hidden, true);
  assert.deepEqual(received.filter(call => call[0] === 'brightness').at(-1), ['brightness', null, null]);
  trackingPreview.hidden = false;
  context.renderWristObserver();
  assert.equal(context.wristObserverFigure.hidden, false, 'retain the marked tracking image if the raw preview is temporarily missing');
  trackingPreview.hidden = true;
  context.renderWristObserver();
  assert.equal(context.wristObserverFigure.hidden, true);
});

test('wrist brightness uses the MolmoAct2 observer endpoint', async () => {
  const h = harness();
  await h.context.applyCameraBrightness('wrist', -32, { apply: { disabled: false }, message: {} });
  assert.equal(h.calls[0][1], '/api/cameras/molmoact2/wrist/brightness');
});


test('conversation-only camera previews show available devices without duplicate placeholders', () => {
  const figures = [{ hidden: false }, { hidden: false }, { hidden: false }];
  const image = index => ({ src: null, closest: () => figures[index], removeAttribute() { this.src = null; } });
  const control = () => ({ receive() {} });
  const context = vm.createContext({
    activeView: 'conversation', currentCameraModel: () => 'conversation', cameraPreviewModelId: null,
    cameraFrameReady: [false, false], wristObserverReady: false, wristObserverFigure: figures[2],
    cameraImages: [image(0), image(1), image(2)],
    brightnessControls: [control(), control(), control()], exposureControls: [control(), control(), control()],
    cameraSettings: [0, 1, 2].map(() => ({ button: { setAttribute() {} } })),
    cameraViews: { classList: { toggle() {} } }, cameraStatus: {}, conversationCameraStatus: {},
    document: { querySelector: selector => selector === '#face-tracking' ? { hidden: true } : {} }, insta360Controls: { receive() {} }, render() {},
  });
  vm.runInContext(extract('function showCameraFrames(', '\nasync function applyCameraBrightness('), context);
  context.showCameraFrames({ observerPreviews: { wrist: { jpeg: 'wrist' } } }, 'conversation');
  assert.deepEqual(figures.map(f => f.hidden), [true, true, false]);
  assert.equal(context.cameraImages[2].src, 'data:image/jpeg;base64,wrist');
  context.showCameraFrames({ observerPreviews: { cam0: { jpeg: 'overhead' }, cam1: { jpeg: 'x5' }, wrist: { jpeg: 'wrist' } } }, 'conversation');
  assert.deepEqual(figures.map(f => f.hidden), [false, false, false]);
  context.showCameraFrames({ observerPreviews: {} }, 'conversation');
  assert.deepEqual(figures.map(f => f.hidden), [true, true, true]);
});
