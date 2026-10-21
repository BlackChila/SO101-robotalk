import test from 'node:test';
import assert from 'node:assert/strict';
import { FaceTrackingControls, faceTrackingEligibility } from './face-tracking.js';
const ready = { view: 'conversation', mode: 'realtime', cameraReady: true, connected: true,
  active: true, sessionId: 'call-1', settingsOpen: true };

test('default browser APIs keep their native receiver when rendering conversation controls', async (t) => {
  const calls = [];
  for (const name of ['setTimeout', 'clearTimeout', 'fetch']) {
    t.mock.method(globalThis, name, function (...args) {
      // Browser host functions reject a controller instance as their receiver.
      assert.ok(this === undefined || this === globalThis, `${name}: invalid receiver`);
      calls.push(name);
      if (name === 'fetch') return Promise.resolve({ ok: true, json: async () => ({ mode: 'off' }) });
      return name === 'setTimeout' ? 1 : undefined;
    });
  }
  const panel = { querySelector: () => ({ addEventListener() {}, removeAttribute() {} }) };
  const control = new FaceTrackingControls(panel);
  assert.doesNotThrow(() => control.setContext(ready));
  await control.poll();
  assert.doesNotThrow(() => control.setContext({ ...ready, view: 'command' }));
  assert.deepEqual(calls, ['setTimeout', 'fetch', 'clearTimeout']);
});

function harness(fetchImpl) {
  const nodes = {};
  const panel = { querySelector(selector) { return nodes[selector] ||= {
    hidden: true, checked: true, addEventListener() {}, removeAttribute(name) { delete this[name]; },
  }; } };
  const calls = [];
  const control = new FaceTrackingControls(panel, { setTimer: () => 1, clearTimer() {},
    fetchImpl: fetchImpl || (async (url, options) => {
      const payload = options.body ? JSON.parse(options.body) : null;
      calls.push({ url, payload, options });
      return { ok: true, json: async () => ({ mode: payload?.action === 'enable' ? 'tracking'
        : payload?.action === 'stop' ? 'off' : 'preview', vision: { available: true } }) };
    }) });
  control.setContext(ready);
  return { control, calls, nodes };
}

test('only an active conversation motor session can enable physical tracking', () => {
  assert.equal(faceTrackingEligibility(ready).enable, true);
  for (const patch of [{ mode: 'unknown' }, { view: 'command' }, { active: false },
    { connected: false }, { sessionId: null }, { voiceOnly: true }, { returning: true },
    { stopping: true }, { taskActive: true }, { taskState: 'loading' },
    { taskState: 'running' }, { taskState: 'stopping' }, { cameraReady: false }]) {
    assert.equal(faceTrackingEligibility({ ...ready, ...patch }).enable, false, JSON.stringify(patch));
  }
  assert.equal(faceTrackingEligibility({ ...ready, active: false }).preview, true);
});

test('rendering and preview never implicitly enable motors; explicit enable carries session authorization', async () => {
  const { control, calls } = harness();
  control.setContext(ready);
  assert.equal(calls.length, 0);
  await control.command('preview');
  assert.deepEqual(calls.map(c => c.payload.action), ['preview']);
  await control.command('enable');
  assert.equal(calls[1].payload.sessionId, 'call-1');
  assert.equal(calls[1].payload.search, true);
  assert.equal(calls[1].options.headers['x-so101-conversation'], 'operator-face-tracking');
  control.setContext({ ...ready, taskActive: true });
  await control.queue;
  assert.equal(calls.at(-1).payload.action, 'disable');
  control.setContext(ready);
  assert.equal(calls.at(-1).payload.action, 'disable');
});

test('leaving conversation stops detection, clears image and never re-enables on return', async () => {
  const { control, calls, nodes } = harness();
  await control.command('preview');
  nodes['[data-face-image]'].src = 'old';
  control.setContext({ ...ready, view: 'command' });
  await control.queue;
  assert.equal(calls.at(-1).payload.action, 'stop');
  assert.equal(nodes['[data-face-image]'].src, undefined);
  control.setContext(ready);
  assert.equal(control.state.mode, 'off');
});

test('delayed polls cannot restore stale tracking status after stop or overlap', async () => {
  let resolve;
  let requests = 0;
  const { control } = harness(async () => {
    requests++;
    return new Promise(done => { resolve = done; });
  });
  const first = control.poll();
  await control.poll();
  assert.equal(requests, 1);
  control.setContext({ ...ready, view: 'command' });
  resolve({ ok: true, json: async () => ({ mode: 'tracking', vision: { preview: { jpeg: 'stale' } } }) });
  await first;
  assert.equal(control.state.mode, 'off');
  assert.equal(control.image.src, undefined);
});

test('pending enable is cancelled if the operator ends the call first', async () => {
  const { control, calls } = harness();
  const enable = control.command('enable');
  control.setContext({ ...ready, active: false });
  await enable;
  assert.equal(calls.length, 0);
});

for (const mode of ['realtime', 'piper', 'local']) {
  test(`${mode} tracking survives status polling and view changes in an idle second tab`, async () => {
    const commands = [];
    let shared = { mode: 'off', sessionId: null };
    const fetchImpl = async (_, options) => {
      if (options.body) {
        const call = JSON.parse(options.body);
        commands.push(call);
        shared = { mode: call.action === 'enable' ? 'tracking' : 'off', sessionId: call.sessionId };
      }
      return { ok: true, json: async () => ({ ...shared }) };
    };
    const owner = harness(fetchImpl).control;
    const observer = harness(fetchImpl).control;
    owner.setContext({ ...ready, mode, introComplete: true });
    await owner.queue;
    const idle = { ...ready, mode, active: false, connected: false, sessionId: null };
    observer.setContext(idle);
    await observer.poll();
    observer.setContext(idle);
    await observer.queue;
    observer.setContext({ ...idle, view: 'command' });
    await observer.queue;
    await observer.command('stop'); // Ending a failed call in another tab is harmless too.
    assert.equal(shared.mode, 'tracking');
    assert.deepEqual(commands.map(c => c.action), ['enable']);
    owner.setContext({ ...ready, mode, active: false, sessionId: null });
    await owner.queue;
    assert.equal(commands.at(-1).action, 'disable');
    assert.equal(commands.at(-1).sessionId, 'call-1');
  });
}

test('queued cleanup retains the old owner instead of targeting a replacement session', async () => {
  const { control, calls } = harness();
  await control.command('enable');
  control.setContext({ ...ready, sessionId: 'call-2', view: 'command' });
  await control.queue;
  assert.equal(calls.at(-1).payload.action, 'stop');
  assert.equal(calls.at(-1).payload.sessionId, 'call-1');
});

test('call ending while enable is in flight still stops its captured session', async () => {
  const calls = [];
  let finishEnable;
  const { control } = harness(async (_, options) => {
    const call = JSON.parse(options.body);
    calls.push(call);
    if (call.action === 'enable') await new Promise(resolve => { finishEnable = resolve; });
    return { ok: true, json: async () => ({ mode: call.action === 'enable' ? 'tracking' : 'off' }) };
  });
  const enabling = control.command('enable');
  await new Promise(resolve => setImmediate(resolve));
  control.setContext({ ...ready, active: false, sessionId: null });
  const stopping = control.command('stop');
  finishEnable();
  await Promise.all([enabling, stopping]);
  assert.deepEqual(calls.map(c => [c.action, c.sessionId]), [['enable', 'call-1'], ['stop', 'call-1']]);
  assert.equal(control.ownedSessionId, null);
  assert.equal(control.ownsPreview, false);
});


test('auto start waits for intro and connection, runs once, and respects manual stop', async () => {
  const { control, calls } = harness();
  control.setContext({ ...ready, introComplete: false });
  await control.queue;
  assert.equal(calls.length, 0);
  control.setContext({ ...ready, introComplete: true, connected: false });
  await control.queue;
  assert.equal(calls.length, 0);
  control.setContext({ ...ready, introComplete: true });
  await control.queue;
  assert.deepEqual(calls.map(c => c.payload.action), ['enable']);
  await control.command('disable');
  control.setContext({ ...ready, introComplete: true });
  await control.queue;
  assert.deepEqual(calls.map(c => c.payload.action), ['enable', 'disable']);
  control.setContext({ ...ready, introComplete: true, sessionId: 'call-2' });
  await control.queue;
  assert.equal(calls.at(-1).payload.sessionId, 'call-2');
  assert.equal(calls.at(-1).payload.action, 'enable');
});

test('automatic enable is cancelled by call ending and never starts after manipulation', async () => {
  const { control, calls } = harness();
  control.setContext({ ...ready, introComplete: true });
  control.setContext({ ...ready, active: false });
  await control.queue;
  assert.equal(calls.length, 0);
  control.setContext({ ...ready, sessionId: 'call-2', introComplete: true, taskEverStarted: true });
  await control.queue;
  assert.equal(calls.length, 0);
});

test('settings only control the tracking image, while automatic tracking stays active', async () => {
  const { control, calls } = harness();
  control.setContext({ ...ready, introComplete: true, settingsOpen: false });
  await control.queue;
  assert.equal(calls.length, 1);
  assert.equal(calls[0].payload.action, 'enable');
  control.state.vision = { preview: { jpeg: 'current-frame' } };
  control.render();
  assert.equal(control.image.hidden, true);
  assert.equal(control.panel.hidden, true);
  control.setContext({ ...ready, introComplete: true, settingsOpen: true });
  assert.equal(control.image.src, 'data:image/jpeg;base64,current-frame');
  assert.equal(control.panel.hidden, false);
  control.setContext({ ...ready, introComplete: true, settingsOpen: false });
  await control.queue;
  assert.equal(control.image.hidden, true);
  assert.equal(control.panel.hidden, true);
  assert.equal(control.state.mode, 'tracking');
  assert.equal(calls.length, 1);
});

test('search direction button persists preference and includes it on activation', async () => {
  let click;
  const button = { addEventListener(event, callback) { click = callback; }, setAttribute() {} };
  const saved = new Map([['so101-face-search-direction', 'left']]);
  const nodes = {};
  const panel = { querySelector(s) { return nodes[s] ||= { checked: true, addEventListener() {}, removeAttribute() {} }; } };
  const payloads = [];
  const control = new FaceTrackingControls(panel, { directionButton: button,
    storage: { getItem: k => saved.get(k), setItem: (k,v) => saved.set(k,v) },
    setTimer: () => 1, clearTimer() {}, fetchImpl: async (_, options) => {
      payloads.push(JSON.parse(options.body));
      return { ok: true, json: async () => ({ mode: 'tracking' }) };
    } });
  control.setContext(ready);
  assert.match(button.textContent, /left/);
  await control.command('enable');
  assert.equal(payloads[0].searchDirection, 'left');
  click();
  assert.match(button.textContent, /right/);
  assert.equal(saved.get('so101-face-search-direction'), 'right');
  assert.equal(payloads.length, 1); // Settings never move the running arm.
});

for (const mode of ['piper', 'local']) {
  test(`${mode} uses the same intro, session, task and camera gates without a WebRTC dependency`, async () => {
    const { control, calls } = harness();
    control.setContext({ ...ready, mode, introComplete: true, connected: false });
    await control.queue;
    assert.equal(calls.length, 0);
    control.setContext({ ...ready, mode, introComplete: true });
    await control.queue;
    assert.equal(calls.at(-1).payload.action, 'enable');
    control.setContext({ ...ready, mode, introComplete: true, taskActive: true });
    await control.queue;
    assert.equal(calls.at(-1).payload.action, 'disable');
    control.setContext({ ...ready, mode, introComplete: true, taskEverStarted: true });
    await control.queue;
    assert.equal(calls.at(-1).payload.action, 'disable');
    control.rearmAfterReset('call-1');
    await control.queue;
    assert.equal(calls.at(-1).payload.action, 'enable');
  });
}
