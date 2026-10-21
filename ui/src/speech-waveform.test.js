import test from 'node:test';
import assert from 'node:assert/strict';
import { PlaybackAmplitude, SpeechWaveform } from './speech-waveform.js';

const tone = amplitude => Float32Array.from({ length: 512 }, (_, i) => amplitude * Math.sin(i * .17));

function harness() {
  const styles = new Map();
  const frames = new Map();
  let id = 0, time = 0;
  const waveform = new SpeechWaveform({ style: { setProperty: (key, value) => styles.set(key, value) } }, {
    requestFrame(callback) { frames.set(++id, callback); return id; },
    cancelFrame(key) { frames.delete(key); },
  });
  const player = { paused: false, muted: false, ended: false, volume: 1, readyState: 4 };
  const context = { state: 'running' };
  const analyser = { fftSize: 512, amplitude: .14, getFloatTimeDomainData(samples) { samples.set(tone(this.amplitude)); } };
  return { waveform, player, context, analyser, frames,
    level: () => Number(styles.get('--speech-level')),
    step(count = 1) {
      for (let i = 0; i < count; i++) {
        const queued = [...frames.values()];
        frames.clear();
        time += 1000 / 60;
        for (const callback of queued) callback(time);
      }
    },
  };
}

test('actual sample amplitude distinguishes quiet and loud speech and decays to silence', () => {
  const quiet = new PlaybackAmplitude(), loud = new PlaybackAmplitude();
  for (let i = 0; i < 60; i++) {
    quiet.sample(tone(.015), 1 / 60);
    loud.sample(tone(.15), 1 / 60);
  }
  assert.ok(loud.level > .7);
  assert.ok(quiet.level < loud.level / 2);
  for (let i = 0; i < 90; i++) loud.sample(new Float32Array(512), 1 / 60);
  assert.equal(loud.level, 0);
  assert.equal(loud.sample(new Float32Array([NaN]), 1 / 60), 0);
});

test('only audible playback drives the bars, including voice-only use without any motor session', () => {
  for (const patch of [{ paused: true }, { muted: true }, { volume: 0 }, { ended: true }, { readyState: 1 }]) {
    const h = harness();
    h.waveform.observeAnalyser(h.analyser, { context: h.context, player: h.player });
    h.step(20);
    assert.ok(h.level() > .7);
    Object.assign(h.player, patch);
    h.step(90);
    assert.equal(h.level(), 0, JSON.stringify(patch));
    assert.equal(h.frames.size, 1);
    h.waveform.stop();
    assert.equal(h.frames.size, 0);
  }
});

test('suspended playback quiets the display; closed contexts and stale players stop sampling', () => {
  const h = harness();
  let current = true;
  h.waveform.observeAnalyser(h.analyser, { context: h.context, player: h.player, isCurrent: () => current });
  h.step(20);
  h.context.state = 'suspended';
  h.step(90);
  assert.equal(h.level(), 0);
  h.context.state = 'running';
  h.step(20);
  assert.ok(h.level() > .7);
  current = false;
  h.step();
  assert.equal(h.level(), 0);
  assert.equal(h.frames.size, 0);
  h.waveform.observeAnalyser(h.analyser, { context: h.context, player: h.player });
  h.context.state = 'closed';
  h.step();
  assert.equal(h.frames.size, 0);
});

test('replacing audio cleans up old ownership and late cleanup cannot clear new speech', () => {
  const h = harness();
  let disconnected = 0;
  const oldStop = h.waveform.observeAnalyser(h.analyser, {
    context: h.context, player: h.player, disconnect() { disconnected++; },
  });
  h.waveform.observeAnalyser(h.analyser, { context: h.context, player: h.player });
  assert.equal(disconnected, 1);
  h.step(20);
  const level = h.level();
  oldStop();
  assert.equal(h.level(), level);
  assert.equal(h.frames.size, 1);
  h.waveform.stop();
  assert.equal(h.level(), 0);
});

test('Realtime stream uses a silent independent analysis branch and cleans it up once', () => {
  const h = harness();
  const edges = [], disconnected = [];
  const node = name => ({ gain: {}, connect(to) { edges.push([name, to]); }, disconnect() { disconnected.push(name); } });
  const source = node('source'), gain = node('gain');
  Object.assign(h.analyser, node('analyser'));
  Object.assign(h.context, {
    createMediaStreamSource: () => source, createAnalyser: () => h.analyser,
    createGain: () => gain, destination: {},
  });
  h.waveform.observeStream(h.context, {}, { player: h.player });
  assert.equal(gain.gain.value, 0);
  assert.deepEqual(edges, [['source', h.analyser], ['analyser', gain], ['gain', h.context.destination]]);
  h.step(20);
  assert.ok(h.level() > .7);
  h.waveform.stop(); h.waveform.stop();
  assert.deepEqual(disconnected, ['source', 'analyser', 'gain']);
});

test('an analysis error stops only the optional visualization', () => {
  const h = harness();
  h.analyser.getFloatTimeDomainData = () => { throw Error('context lost'); };
  h.waveform.observeAnalyser(h.analyser, { context: h.context, player: h.player });
  assert.doesNotThrow(() => h.step());
  assert.equal(h.level(), 0);
  assert.equal(h.frames.size, 0);
});
