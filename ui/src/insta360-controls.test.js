import test from 'node:test';
import assert from 'node:assert/strict';
import { Insta360Controls } from './insta360-controls.js';

function harness() {
  const element = (extra = {}) => ({ disabled: false, textContent: '', ...extra, listeners: {},
    addEventListener(name, callback) { this.listeners[name] = callback; } });
  const inputs = ['yaw', 'pitch', 'roll', 'zoom'].map((axis) => element({ dataset: { axis }, value: '0' }));
  const nodes = Object.fromEntries(['[data-apply]', '[data-reset]', '[data-message]',
    ...inputs.map((input) => `[data-value="${input.dataset.axis}"]`)].map((key) => [key, element()]));
  const panel = { hidden: true, querySelectorAll: () => inputs, querySelector: (key) => nodes[key] };
  const calls = [];
  const controls = new Insta360Controls(panel, (view) => { calls.push(view); });
  return { controls, panel, inputs, nodes, calls };
}
const defaults = { yaw: 65, pitch: 15, roll: 55, zoom: 1 };
const view = { ...defaults, defaults };

test('only an available X5 view exposes controls; other profiles and fallback hide them', () => {
  const h = harness();
  h.controls.receive(null);
  h.controls.render(true, false);
  assert.equal(h.panel.hidden, true);
  h.controls.receive(view);
  h.controls.render(true, false);
  assert.equal(h.panel.hidden, false);
  h.controls.render(false, false);
  assert.equal(h.panel.hidden, true);
  h.controls.receive(null);
  h.controls.render(true, false);
  assert.equal(h.panel.hidden, true);
});

test('preview polling preserves unapplied changes, and apply sends orientation and zoom', () => {
  const h = harness();
  h.controls.receive(view);
  h.controls.render(true, false);
  h.inputs[0].value = '-42.5';
  h.inputs[0].listeners.input();
  h.inputs[3].value = '1.3';
  h.inputs[3].listeners.input();
  h.controls.receive(view);
  assert.equal(h.inputs[0].value, '-42.5');
  assert.equal(h.nodes['[data-value="yaw"]'].textContent, '-42.5°');
  assert.equal(h.nodes['[data-value="zoom"]'].textContent, '1.3×');
  h.controls.apply.listeners.click();
  assert.deepEqual(h.calls, [{ yaw: -42.5, pitch: 15, roll: 55, zoom: 1.3 }]);
  h.controls.receive({ ...view, yaw: -42.5 }, true);
  assert.equal(h.controls.apply.disabled, true);
  assert.match(h.controls.message.textContent, /saved/);
});

test('busy controls cannot apply or reset; defaults require an explicit apply', () => {
  const h = harness();
  h.controls.receive({ ...view, yaw: -30 });
  h.controls.render(true, true);
  assert.ok(h.inputs.every((input) => input.disabled));
  h.controls.apply.listeners.click();
  h.controls.reset.listeners.click();
  assert.equal(h.calls.length, 0);
  assert.equal(Number(h.inputs[0].value), -30);
  h.controls.render(true, false);
  h.controls.reset.listeners.click();
  assert.equal(h.calls.length, 0);
  assert.equal(h.controls.apply.disabled, false);
  h.controls.apply.listeners.click();
  assert.deepEqual(h.calls, [defaults]);
});
