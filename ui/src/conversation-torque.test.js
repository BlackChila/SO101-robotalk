import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
const extract = (start, end) => source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start)));

function harness() {
  const calls = [];
  const context = vm.createContext({
    backendReady: true, phase: 'idle', teleopActionGeneration: 0,
    status: { resetRunning: false, torqueRunning: false, torqueAvailable: true, torqueAction: 'on' },
    conversationTorqueFeedback: { hidden: true, dataset: {} },
    render() {}, setFeedback: (message, kind) => calls.push(['feedback', message, kind]),
    readJson: async response => response,
    fetch: async (url, options) => { calls.push(['fetch', url, options]); return { message: 'Drehmoment bestätigt.' }; },
    refreshStatus: async () => calls.push(['refresh']),
  });
  vm.runInContext(extract('function setTorqueFeedback(', "\ntorqueOnButton.addEventListener("), context);
  return { context, calls };
}

test('conversation torque controls reuse the operator-click endpoints and show results', async () => {
  for (const turningOn of [true, false]) {
    const h = harness();
    await h.context.setTorque(turningOn);
    const request = h.calls.find(call => call[0] === 'fetch');
    assert.equal(request[1], `/api/torque/${turningOn ? 'on' : 'off'}`);
    assert.equal(request[2].method, 'POST');
    assert.equal(request[2].headers['X-SO101-Torque'], 'operator-click');
    assert.equal(h.context.conversationTorqueFeedback.hidden, false);
    assert.equal(h.context.conversationTorqueFeedback.textContent, 'Drehmoment bestätigt.');
    assert.equal(h.context.phase, 'idle');
    assert.ok(h.calls.some(call => call[0] === 'refresh'));
  }
});

test('torque errors are visible in Gespräch and busy controls send no requests', async () => {
  const h = harness();
  h.context.fetch = async () => { throw new Error('Controller belegt'); };
  await h.context.setTorque(false);
  assert.match(h.context.conversationTorqueFeedback.textContent, /Controller belegt/);
  assert.equal(h.context.conversationTorqueFeedback.dataset.state, 'error');
  h.context.status.resetRunning = true;
  h.context.fetch = async () => { throw new Error('Must not make a request'); };
  const before = h.calls.length;
  await h.context.setTorque(true);
  await h.context.setTorque(false);
  assert.equal(h.calls.length, before);
});

test('torque-off retains the reset-holder release path', async () => {
  const h = harness();
  h.context.status.resetHolding = true;
  h.context.status.torqueAction = 'off';
  h.context.phase = 'inferring';
  await h.context.setTorque(false);
  const request = h.calls.find(call => call[0] === 'fetch');
  assert.equal(request[1], '/api/reset/release');
  assert.equal(request[2].headers['X-SO101-Reset'], 'operator-click');
});

test('settings toggle reveals cameras without issuing a hardware request', () => {
  const context = vm.createContext({
    activeView: 'conversation', status: { cameraModel: 'conversation' },
    cameraPreviewModelId: 'conversation', cameraOpening: false,
    conversationSettings: { render() {}, button: {}, open: false },
    renderWristObserver() {}, conversationCameraStatus: {}, conversationCamerasSection: { hidden: true },
    fetch() { throw new Error('Settings rendering must not change torque'); },
  });
  vm.runInContext(extract('function renderConversationSettings()', '\nconst activeView'), context);
  context.renderConversationSettings();
  assert.equal(context.conversationCamerasSection.hidden, true);
  context.conversationSettings.open = true;
  context.renderConversationSettings();
  assert.equal(context.conversationCamerasSection.hidden, false);
  context.conversationSettings.open = false;
  context.renderConversationSettings();
  assert.equal(context.conversationCamerasSection.hidden, true);
});
