import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { setImmediate } from 'node:timers/promises';
import { RealtimeTaskFeedback } from './realtime-task-feedback.js';
import { languageInstruction } from './conversation-language.js';

test('German greeting is requested once, without tools, and queues user speech', () => {
  const events = [];
  const scheduler = new RealtimeTaskFeedback(e => events.push(e), () => {});
  scheduler.greet();
  scheduler.greet();
  assert.equal(events.length, 1);
  assert.equal(events[0].type, 'response.create');
  assert.equal(events[0].response.tool_choice, 'none');
  assert.match(events[0].response.instructions, /Deutsch/);
  assert.match(events[0].response.instructions, /ausschließlich auf Deutsch/);
  assert.match(events[0].response.instructions, /Hallo, ich bin SO-101\. Was kann ich für dich tun\?/);
  assert.match(events[0].response.instructions, /SO-101/);
  scheduler.userTurnCommitted('answer');
  assert.equal(events.length, 1);
  scheduler.responseFinished();
  assert.equal(events.length, 2);
  assert.equal(events[1].response.tool_choice, 'auto');
  scheduler.responseFinished();
  scheduler.greet();
  assert.equal(events.length, 2);
  scheduler.reset();
  scheduler.greet();
  assert.equal(events.length, 3);
});

const main = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
const code = main.slice(main.indexOf('async function greetLocalConversation('), main.indexOf('\nasync function stopConversationTask('));
function harness(mode = 'realtime', voiceOnly = false) {
  const calls = [];
  let finishIntro;
  const intro = new Promise(resolve => { finishIntro = resolve; });
  const track = { addEventListener() {}, stop() {} };
  const c = vm.createContext({
    conversationActive: false, conversationGeneration: 0, conversationMode: mode, conversationLanguage: 'German',
    conversationStopping: null, conversationReturning: false,
    conversationMotionId: null, conversationRequest: null,
    realtimeTaskCalls: new Set(), realtimeTaskFeedback: { reset() {} },
    conversationTaskFeedback: {}, renderConversationTaskStop() {},
    setConversationPhase() {}, localStorage: { removeItem() {} }, sessionStorage: { setItem() {} },
    AbortController, render() {}, conversationSpeakerName: () => 'Selected voice',
    AudioContext: class {
      state = 'running'; async resume() {}
      createMediaStreamSource() { return { connect() {} }; }
      createAnalyser() { return { connect() {} }; }
      createGain() { return { gain: {}, connect() {} }; }
    },
    readJson: async response => response,
    fetch: async url => {
      if (url === '/api/conversation/greet') {
        calls.push({ op: 'model-greeting' });
        return { reply: 'Generated Qwen opening', responseId: 'resp_opening' };
      }
      return { followerPortAvailable: true, realtimeTaskProtocol: 4, localTaskProtocol: 1, localTtsEngines: ['piper', 'qwen'] };
    },
    speakConversation: async text => { calls.push({ op: 'speak', text }); },
    listenForConversation: () => { calls.push({ op: 'listen' }); },
    localConversation: {
      start: async () => true,
      greet: async () => { calls.push({ op: 'model-greeting' }); await c.speakConversation('Generated Piper opening'); },
    },
    postConversationMotion: async (op, opts) => {
      calls.push({ op, opts });
      return voiceOnly ? { status: 'voice-only' } : { status: 'starting', sessionId: 'arm' };
    },
    setInterval: () => 1,
    waitForConversationIntro: async () => { calls.push({ op: 'wait-intro' }); await intro; },
    navigator: { mediaDevices: { getUserMedia: async () => { calls.push({ op: 'microphone' }); return { getTracks: () => [track], getAudioTracks: () => [track] }; } } },
    startRealtimeSession: async () => { calls.push({ op: 'realtime' }); },
    preloadRealtimeMolmo: async () => { calls.push({ op: 'preload' }); return { ready: true }; },
    stopConversationMotion: async () => {},
    endConversation: () => { calls.push({ op: 'error' }); },
  });
  vm.runInContext(code, c);
  return { c, calls, finishIntro };
}

for (const mode of ['piper', 'local']) {
  test(`${mode} mutes recorded welcome and generates speech before listening`, async () => {
    const h = harness(mode);
    const running = h.c.startConversation();
    await setImmediate();
    assert.equal(h.calls[0].opts.realtimeIntro, true);
    assert.ok(!h.calls.some(c => c.op === 'model-greeting'));
    h.finishIntro();
    await running;
    assert.ok(!h.calls.some(c => c.op === 'error'));
    assert.deepEqual(h.calls.filter(c => ['model-greeting', 'speak', 'listen'].includes(c.op)).map(c => c.op),
      ['model-greeting', 'speak', 'listen']);
    assert.equal(h.c.conversationResponseId, undefined);
  });

  test(`${mode} also starts with a generated greeting without an arm`, async () => {
    const h = harness(mode, true);
    await h.c.startConversation();
    assert.deepEqual(h.calls.filter(c => ['model-greeting', 'speak', 'listen'].includes(c.op)).map(c => c.op),
      ['model-greeting', 'speak', 'listen']);
  });
}

test('Qwen opening returned after ending the call cannot play or start listening', async () => {
  const h = harness('local', true);
  h.c.localConversation.greet = async () => {
    h.c.conversationActive = false;
    h.c.conversationGeneration++;
    throw new DOMException('Gespräch beendet.', 'AbortError');
  };
  await h.c.startConversation();
  assert.ok(!h.calls.some(c => ['speak', 'listen'].includes(c.op)));
});

test('Qwen with an old backend refuses to open microphone or start arm motion', async () => {
  const h = harness('local');
  h.c.fetch = async () => ({ localTaskProtocol: 1 });
  await h.c.startConversation();
  assert.deepEqual(h.calls.map(c => c.op), ['error']);
});

test('Realtime connects before intro completion and model warmup', async () => {
  const h = harness();
  const running = h.c.startConversation();
  await setImmediate();
  assert.deepEqual(h.calls.map(c => c.op), ['start', 'microphone', 'realtime', 'wait-intro']);
  assert.equal(h.calls[0].opts.realtimeIntro, true);
  assert.equal(h.calls[0].opts.skipIntro, false);
  h.finishIntro();
  await running;
  assert.equal(h.calls.at(-1).op, 'preload');
});

test('stopped startup cannot preload after a late intro completion', async () => {
  const h = harness();
  const running = h.c.startConversation();
  await setImmediate();
  h.c.conversationActive = false;
  h.c.conversationGeneration += 1;
  h.finishIntro();
  await running;
  assert.ok(!h.calls.some(c => c.op === 'preload'));
});

test('queued speech waits until audio drains even after response.done; late duplicate stop cannot release new audio', () => {
  const events = [];
  const scheduler = new RealtimeTaskFeedback(e => events.push(e), () => {});
  scheduler.greet();
  assert.equal(events[0].response.metadata.purpose, 'greeting');
  scheduler.playbackStarted('hello');
  scheduler.userTurnCommitted('question');
  scheduler.responseFinished();
  assert.equal(events.length, 1);
  scheduler.playbackFinished('hello');
  assert.equal(events.length, 2);
  scheduler.playbackStarted('answer');
  scheduler.userTurnCommitted('next-question');
  scheduler.responseFinished();
  scheduler.playbackFinished('hello');
  assert.equal(events.length, 2);
  scheduler.playbackFinished('answer');
  assert.equal(events.length, 3);
});

test('duplicate connection and track events cannot restart greeting or audio playback', async () => {
  const channel = {};
  const players = [];
  let polls = 0;
  let greetings = 0;
  let visualizations = 0;
  const peer = {
    addTrack() {}, createDataChannel: () => channel,
    createOffer: async () => ({ sdp: 'offer' }),
    async setLocalDescription() {}, async setRemoteDescription() {},
  };
  const c = vm.createContext({
    AbortSignal, conversationActive: true, conversationGeneration: 1, conversationLanguage: 'English', languageInstruction,
    realtimeWebSearch: { reset() {} },
    conversationVoiceOnly: true, conversationMotionId: null, realtimeAudioElement: null,
    conversationAudioContext: {},
    conversationWaveform: { observeStream() { visualizations++; } },
    conversationSpeakerValue: () => 'ballad', realtimeMolmoPreloadWarning: '',
    RTCPeerConnection: function () { return peer; },
    fetch: async (url, options) => {
      if (url === '/api/conversation/realtime/token') assert.equal(JSON.parse(options.body).language, 'English');
      return { ok: true, text: async () => 'answer' };
    },
    readJson: async () => ({ value: 'test-token' }),
    waitForRealtimeChannel: async () => {},
    setConversationPhase() {}, sendRealtimeEvent() {}, SPOKEN_BREVITY: '',
    setInterval: () => { polls += 1; return 1; },
    realtimeTaskFeedback: { greet() { greetings += 1; } },
    document: { createElement() {
      const audio = { playCalls: 0, pauseCalls: 0, addEventListener() {},
        async play() { this.playCalls += 1; }, pause() { this.pauseCalls += 1; } };
      players.push(audio); return audio;
    } },
  });
  vm.runInContext(main.slice(main.indexOf('async function startRealtimeSession('),
    main.indexOf('\nasync function answerConversation(')), c);
  await c.startRealtimeSession({ getAudioTracks: () => [{}] }, 1);
  channel.onopen(); channel.onopen();
  assert.equal(greetings, 1);
  assert.equal(polls, 1);
  const track = { kind: 'audio', addEventListener() {} };
  const stream = { getAudioTracks: () => [track] };
  peer.ontrack({ track, streams: [stream] });
  peer.ontrack({ track, streams: [stream] });
  assert.equal(players.length, 1);
  assert.equal(players[0].playCalls, 1);
  assert.equal(players[0].pauseCalls, 0);
  assert.equal(visualizations, 1);
});
