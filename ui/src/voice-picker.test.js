import test from 'node:test';
import assert from 'node:assert/strict';
import { VoicePicker } from './voice-picker.js';

function harness() {
  const node = () => ({ listeners: {}, ownerDocument: { createElement: () => ({}) },
    addEventListener(event, handler) { this.listeners[event] = handler; },
    replaceChildren(...options) { this.options = options; },
    fire(event, detail = {}) { this.listeners[event]({ preventDefault() {}, ...detail }); },
  });
  const select = node();
  let clock = 1000;
  const calls = [];
  const picker = new VoicePicker({ select, now: () => clock,
    onSelect(index) { calls.push(index); picker.render(picker.voices, index, picker.disabled); },
  });
  const voices = [{ value: 'marin', name: 'Marin' }, { value: 'cedar', name: 'Cedar' }, { value: 'alloy', name: 'Alloy' }];
  picker.render(voices, 0, false);
  return { picker, select, calls, tick(ms) { clock += ms; } };
}

test('native heading dropdown changes the same voice selection without replacing its options', () => {
  const h = harness();
  const options = h.select.options;
  h.select.selectedIndex = 1;
  h.select.fire('change');
  assert.deepEqual(h.calls, [1]);
  assert.equal(h.select.options, options);
  assert.equal(h.select.options[1].value, 'cedar');
});

test('wheel accumulates small deltas, cycles both ways and discards old partial gestures', () => {
  const h = harness();
  h.select.fire('wheel', { deltaY: 30 });
  assert.deepEqual(h.calls, []);
  h.select.fire('wheel', { deltaY: 40 });
  h.select.fire('wheel', { deltaY: -70 });
  assert.deepEqual(h.calls, [1, 0]);
  h.select.fire('wheel', { deltaY: 40 });
  h.tick(400);
  h.select.fire('wheel', { deltaY: 40 });
  assert.deepEqual(h.calls, [1, 0]);
  h.select.fire('wheel', { deltaY: 2, deltaMode: 1 });
  assert.deepEqual(h.calls, [1, 0, 1]);
});

test('wheel wraps from the first voice to the last and back', () => {
  const h = harness();
  h.select.fire('wheel', { deltaY: -70 });
  assert.equal(h.select.selectedIndex, 2);
  h.select.fire('wheel', { deltaY: 70 });
  assert.deepEqual(h.calls, [2, 0]);
});

test('active Realtime lock blocks selection and scrolling, and mode changes replace the voice list', () => {
  const h = harness();
  h.picker.render(h.picker.voices, 0, true);
  h.select.fire('wheel', { deltaY: 150 }); h.select.fire('change');
  assert.deepEqual(h.calls, []);
  assert.equal(h.select.disabled, true);
  const voices = [{ value: 'Thorsten', name: 'Thorsten · DE' }, { value: 'Amy', name: 'Amy · US' }];
  h.picker.render(voices, 0, false);
  assert.equal(h.select.options[0].textContent, 'Thorsten · DE');
  h.select.fire('wheel', { deltaY: 70 });
  assert.deepEqual(h.calls, [1]);
  assert.equal(h.select.disabled, false);
});
