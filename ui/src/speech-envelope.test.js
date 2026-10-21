import test from 'node:test';
import assert from 'node:assert/strict';
import { SpeechEnvelope, startSpeechLevelPump } from './speech-envelope.js';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const tone = (amplitude) => Float32Array.from({ length: 512 }, (_, i) => amplitude * Math.sin(i * 0.17));

test('tracks 5 Hz syllables, even after ten minutes of continuous nonzero speech', () => {
  const envelope = new SpeechEnvelope();
  const loud = tone(0.15), quiet = tone(0.012);
  let peak;
  for (let i = 0; i < 40 * 600; i++) {
    const level = envelope.sample(i % 8 < 4 ? loud : quiet);
    assert.ok(level >= 0 && level <= 1);
    if (i % 8 === 3) peak = level;
    if (i % 8 === 7) assert.ok(peak - level > 0.7);
  }
});

test('gain adapts to quieter speech; silence returns to zero', () => {
  const envelope = new SpeechEnvelope();
  for (let i = 0; i < 40; i++) envelope.sample(tone(0.4));
  for (let i = 0; i < 240; i++) envelope.sample(tone(0.04));
  assert.ok(envelope.level > 0.9);
  for (let i = 0; i < 12; i++) envelope.sample(new Float32Array(512));
  assert.equal(envelope.level, 0);
});

test('a delayed request cannot queue old audio and stopped pump ignores late errors', async () => {
  let release;
  let calls = 0, errors = 0;
  const stop = startSpeechLevelPump({ interval: 2, enabled: () => true, read: () => 0.5,
    send: () => { calls++; return new Promise((_, reject) => { release = reject; }); },
    onError: () => errors++,
  });
  try {
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.equal(calls, 1);
    stop();
    release(new Error('late request'));
    await new Promise(resolve => setTimeout(resolve, 10));
    assert.equal(errors, 0);
    assert.equal(calls, 1);
  } finally { stop(); }
});

test('response.done never sends speech-end while buffered audio can still play', () => {
  const source = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
  const start = source.indexOf('function handleRealtimeEvent(');
  const end = source.indexOf('\nasync function startRealtimeSession', start);
  const sent = [];
  const context = vm.createContext({ console: { info() {} }, conversationActive: true,
    conversationGeneration: 1, conversationVoiceOnly: false, realtimeSpeaking: true,
    conversationMotionId: 'session', realtimeTaskActive: false,
    realtimeTaskFeedback: { playing: new Set(['greeting']), responseFinished() {} }, setConversationPhase() {},
    postConversationMotion: (...args) => { sent.push(args); return Promise.resolve(); },
  });
  vm.runInContext(source.slice(start, end), context);
  vm.runInContext(`handleRealtimeEvent({data: JSON.stringify({type:'response.done', response:{status:'completed',output:[]}})}, 1)`, context);
  assert.deepEqual(sent, []);
  assert.equal(context.realtimeSpeaking, true);
});
