import test from 'node:test';
import assert from 'node:assert/strict';
import { CameraSettingsToggle, CameraBrightnessControls } from './camera-settings.js';

const element = () => ({ hidden: false, disabled: false, value: '0', textContent: '', listeners: {}, attrs: {},
  addEventListener(name, handler) { this.listeners[name] = handler; },
  setAttribute(name, value) { this.attrs[name] = value; } });

test('gear opens and closes its own panel; missing camera closes and hides settings', () => {
  const button = element(); const panel = element(); let toggled = 0;
  const settings = new CameraSettingsToggle(button, panel, () => toggled++);
  settings.render(true);
  assert.equal(panel.hidden, true);
  button.listeners.click();
  assert.equal(panel.hidden, false);
  assert.equal(button.attrs['aria-expanded'], 'true');
  button.listeners.click();
  assert.equal(panel.hidden, true);
  button.listeners.click();
  settings.render(false);
  assert.equal(panel.hidden, true);
  assert.equal(button.hidden, true);
  assert.equal(toggled, 3);
});

test('brightness uses native limits, preserves drafts and sends the real fallback source', () => {
  const nodes = Object.fromEntries(['input', 'output', '[data-brightness-apply]', '[data-brightness-reset]', '[data-brightness-message]'].map((key) => [key, element()]));
  const calls = [];
  const controls = new CameraBrightnessControls({ querySelector: (key) => nodes[key] }, (role, value) => calls.push({ role, value }));
  const native = { min: -256, max: 256, step: 1, default: 0, value: 20 };
  controls.receive(native, 'cam1');
  controls.render(false);
  assert.equal(nodes.input.min, -256);
  assert.equal(nodes.input.max, 256);
  nodes.input.value = '-15'; nodes.input.listeners.input();
  controls.receive(native, 'cam1');
  assert.equal(nodes.input.value, '-15');
  controls.apply.listeners.click();
  assert.deepEqual(calls, [{ role: 'cam1', value: -15 }]);
  controls.render(true);
  controls.apply.listeners.click();
  assert.equal(calls.length, 1);
  controls.render(false);
  controls.receive({ ...native, value: -15 }, 'cam1', true);
  assert.equal(controls.apply.disabled, true);
  controls.receive(null, 'cam0'); controls.render(false);
  assert.equal(nodes.input.disabled, true);
});

test('exposure displays milliseconds, restores the profile default and hides unsupported sources', () => {
  const nodes = Object.fromEntries(['input', 'output', '[data-exposure-apply]', '[data-exposure-reset]', '[data-exposure-message]'].map((key) => [key, element()]));
  const panel = { hidden: true, querySelector: (key) => nodes[key] };
  const calls = [];
  const controls = new CameraBrightnessControls(panel, (role, value) => calls.push({ role, value }), 'exposure');
  const native = { min: 1, max: 333, step: 1, default: 80, value: 50 };
  controls.receive(native, 'scene'); controls.render(false);
  assert.equal(panel.hidden, false);
  assert.equal(nodes.output.textContent, '5.0 ms');
  nodes.input.value = '30'; nodes.input.listeners.input();
  controls.receive(native, 'scene');
  assert.equal(nodes.output.textContent, '3.0 ms');
  controls.apply.listeners.click();
  assert.deepEqual(calls, [{ role: 'scene', value: 30 }]);
  controls.reset.listeners.click();
  assert.equal(nodes.output.textContent, '8.0 ms');
  controls.receive(null, 'cam1'); controls.render(false);
  assert.equal(panel.hidden, true);
  assert.equal(nodes.input.disabled, true);
});
