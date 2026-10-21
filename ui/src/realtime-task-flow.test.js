import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { setImmediate } from 'node:timers/promises';
import { RealtimeTaskFeedback } from './realtime-task-feedback.js';
import { sceneMessages } from './realtime-scene.js';

const main = readFileSync(new URL('./main.js', import.meta.url), 'utf8');
const handlers = main.slice(main.indexOf('function sendRealtimeEvent('), main.indexOf('async function startRealtimeSession('));
function harness({ startStatus = 200 } = {}) {
  const requests = [], events = [];
  const feedback = { hidden: true, textContent: '' };
  const context = vm.createContext({
    AbortSignal, TextEncoder, sceneMessages, realtimePeer: { sctp: { maxMessageSize: 65536 } },
    realtimeWebSearch: { search: async query => {
      requests.push({ search: query });
      return { status: 'ok', answer: 'Aktuelle Antwort', citations: [] };
    } },
    status: { taskRun: null }, conversationRestartPending: false, conversationResetEpoch: 0,
    resetConversationRobot: async id => { requests.push({ reset: id }); return { status: "reset" }; }, renderConversationTaskStop() {},
    conversationActive: true, conversationGeneration: 1, conversationMotionId: 'a'.repeat(32),
    conversationVoiceOnly: false, realtimeTaskActive: false, realtimeTaskEverStarted: false,
    realtimeSpeaking: false, realtimeSpeechGripperAvailable: true, realtimeTaskCalls: new Set(),
    conversationTaskFeedback: feedback, conversationTaskStop: { hidden: true },
    realtimeTaskFeedback: new RealtimeTaskFeedback(e => events.push(e), message => { feedback.textContent = message; }),
    realtimeChannel: { readyState: 'open', send: raw => events.push(JSON.parse(raw)) },
    setConversationPhase() {}, conversationSpeakerName: () => 'Roboter',
    postConversationMotion: async () => ({}), endConversation: () => { throw Error('unexpected end'); },
    readJson: async r => { if (!r.ok) throw Error(r.body.detail); return r.body; },
    fetch: async (url, options = {}) => {
      requests.push({ url, body: options.body ? JSON.parse(options.body) : null });
      const status = url.endsWith('/start') ? startStatus : 200;
      const body = status !== 200 ? { detail: 'Gesprächsarm ist nicht bereit.' }
        : url.endsWith('/start') ? { status: 'updated', taskRun: { id: 'run-1', state: 'running' } }
        : url === '/api/task/status' ? { taskRun: { state: 'failed', message: 'Kamera Insta360 X5 nicht verbunden' } }
        : { state: 'holding' };
      return { status, ok: status === 200, body };
    },
  });
  vm.runInContext(handlers, context);
  const deliver = data => context.handleRealtimeEvent({ data: JSON.stringify(data) }, 1);
  return { context, requests, events, feedback, deliver };
}
async function command(h, id = 'call-1', completion = 'completed') {
  h.deliver({ type: 'response.created' });
  h.deliver({ type: 'response.done', response: { status: completion, output: [
    { type: 'message', content: [{ type: 'output_audio', transcript: 'Ich werde jetzt den Ball in den Topf legen.' }] },
    { type: 'function_call', name: 'execute_molmo_task', call_id: id, arguments: JSON.stringify({ instruction: 'Lege den Ball in den Topf.' }) },
  ] } });
  await setImmediate();
}

test('announced tool call starts immediately, without any confirmation exchange', async () => {
  const h = harness();
  await command(h);
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, '/api/conversation/task/start');
  assert.equal(h.requests[0].body.callId, 'call-1');
  assert.equal(h.context.realtimeTaskActive, true);
  assert.ok(h.events.some(e => e.item?.type === 'function_call_output'));
  assert.equal(h.events.filter(e => e.type === 'response.create').length, 0);
  h.deliver({ type: 'input_audio_buffer.speech_started', item_id: 'answer' });
  h.deliver({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'answer', transcript: 'Ja' });
  await setImmediate();
  assert.equal(h.requests.length, 1, 'speech transcriptions must not trigger task execution');
});

test('a second task works during a run and duplicate tool calls are ignored', async () => {
  const h = harness();
  await command(h);
  await command(h);
  assert.equal(h.requests.length, 1);
  await command(h, 'call-2');
  assert.equal(h.requests.length, 2);
  assert.match(h.feedback.textContent, /new instruction/);
  await h.context.pollRealtimeTask(1);
  assert.equal(h.context.realtimeTaskActive, false);
  await command(h, 'call-3');
  assert.equal(h.context.realtimeTaskActive, true);
  assert.equal(h.requests.filter(r => r.url.endsWith('/start')).length, 3);
});

test('cancelled responses and voice-only sessions never execute a task', async () => {
  const h = harness();
  await command(h, 'call-1', 'cancelled');
  assert.equal(h.requests.length, 0);
  h.context.conversationVoiceOnly = true;
  await command(h, 'call-2');
  assert.equal(h.requests.length, 0);
  assert.equal(h.context.realtimeTaskActive, false);
});

test('controller failures reach the dialogue', async () => {
  const h = harness();
  await command(h);
  h.deliver({ type: 'response.created' });
  await h.context.pollRealtimeTask(1);
  assert.match(h.feedback.textContent, /Insta360 X5/);
  assert.equal(h.events.filter(e => e.type === 'response.create').length, 0);
  h.deliver({ type: 'response.done', response: { status: 'completed', output: [] } });
  assert.equal(h.events.filter(e => e.type === 'response.create').length, 1);
});

test('start errors are explained without claiming an active task', async () => {
  const h = harness({ startStatus: 409 });
  await command(h);
  assert.equal(h.context.realtimeTaskActive, false);
  assert.match(h.feedback.textContent, /nicht bereit/);
  assert.ok(h.events.some(e => e.type === 'response.create'));
});

test('speech while the arm runs creates a new tool-capable dialogue response', async () => {
  const h = harness();
  await command(h);
  h.deliver({ type: 'input_audio_buffer.speech_started', item_id: 'next' });
  h.deliver({ type: 'input_audio_buffer.committed', item_id: 'next' });
  const replies = h.events.filter(e => e.type === 'response.create');
  assert.equal(replies.length, 1);
  assert.equal(replies[0].response.tool_choice, 'auto');
  h.deliver({ type: 'input_audio_buffer.committed', item_id: 'next' });
  assert.equal(h.events.filter(e => e.type === 'response.create').length, 1);
  await command(h, 'call-next');
  assert.equal(h.requests.filter(r => r.url.endsWith('/start')).length, 2);
});

test('speech during an announcement waits for the tool result, then gets a response', async () => {
  const h = harness();
  let releaseStart;
  h.context.fetch = async () => new Promise(resolve => {
    releaseStart = () => resolve({ ok: true, body: { status: 'loading', taskRun: { id: 'run', state: 'loading' } } });
  });
  h.deliver({ type: 'response.created' });
  h.deliver({ type: 'input_audio_buffer.speech_started', item_id: 'next' });
  h.deliver({ type: 'input_audio_buffer.committed', item_id: 'next' });
  assert.equal(h.events.filter(e => e.type === 'response.create').length, 0);
  await command(h);
  assert.equal(h.events.filter(e => e.type === 'response.create').length, 0, 'tool result is still pending');
  releaseStart();
  await setImmediate();
  const resultIndex = h.events.findIndex(e => e.item?.type === 'function_call_output');
  const responseIndex = h.events.findIndex(e => e.type === 'response.create');
  assert.ok(resultIndex >= 0 && responseIndex > resultIndex);
  assert.equal(h.events[responseIndex].response.tool_choice, 'auto');
  assert.ok(!h.events.some(e => e.type === 'response.cancel'));
});

test('voice-only sessions use the same scheduler and reset drops queued speech', async () => {
  const h = harness();
  h.context.conversationVoiceOnly = true;
  h.deliver({ type: 'input_audio_buffer.speech_started', item_id: 'voice' });
  h.deliver({ type: 'input_audio_buffer.committed', item_id: 'voice' });
  assert.equal(h.events.length, 1);
  assert.equal(h.events[0].type, 'response.create');
  h.context.realtimeTaskFeedback.responseStarted();
  h.context.realtimeTaskFeedback.userTurnCommitted('pending');
  h.context.realtimeTaskFeedback.reset();
  h.context.realtimeTaskFeedback.responseFinished();
  assert.equal(h.events.length, 1);
});

test('semantic reset tool uses the same dialogue and is deduplicated', async () => {
  const h = harness();
  const event = { type: 'response.done', response: { status: 'completed', output: [
    { type: 'function_call', name: 'reset_robot', call_id: 'reset-1', arguments: '{}' },
  ] } };
  h.deliver(event);
  await setImmediate();
  h.deliver(event);
  await setImmediate();
  assert.deepEqual(h.requests.filter(r => r.reset), [{ reset: 'reset-1' }]);
  assert.equal(h.context.conversationActive, true);
  assert.ok(h.events.some(e => e.item?.type === 'function_call_output' && e.item.call_id === 'reset-1'));
});


test('reset takes precedence over movement in the same response and answers both calls', async () => {
  const h = harness();
  h.deliver({ type: 'response.done', response: { status: 'completed', output: [
    { type: 'function_call', name: 'execute_molmo_task', call_id: 'move', arguments: '{"instruction":"Move"}' },
    { type: 'function_call', name: 'reset_robot', call_id: 'reset', arguments: '{}' },
  ] } });
  await setImmediate();
  assert.deepEqual(h.requests, [{ reset: 'reset' }]);
  const outputs = h.events.filter(e => e.item?.type === 'function_call_output');
  assert.equal(outputs.length, 2);
  assert.ok(JSON.parse(outputs.find(e => e.item.call_id === 'move').item.output).error);
  assert.equal(JSON.parse(outputs.find(e => e.item.call_id === 'reset').item.output).status, 'reset');
});

function sceneCall(h, callId = 'scene-1') {
  h.deliver({ type: 'response.created' });
  h.deliver({ type: 'response.done', response: { status: 'completed', output: [
    { type: 'function_call', name: 'look_at_scene', call_id: callId, arguments: '{}' },
  ] } });
}
const snapshot = { status: 'ok', unavailable: [], images: ['overhead', 'wrist'].map(camera => ({
  camera, capturedAt: 123., width: 640, height: 480, imageUrl: 'data:image/jpeg;base64,AA==',
})) };

test('scene tool sends two labeled images before one response, without motor access or visible settings', async () => {
  const h = harness();
  h.context.conversationVoiceOnly = true;
  h.context.conversationMotionId = null;
  h.context.fetch = async (url, opts) => {
    h.requests.push({ url, opts });
    return { ok: true, body: snapshot };
  };
  sceneCall(h);
  await setImmediate();
  assert.deepEqual(h.requests.map(r => r.url), ['/api/conversation/realtime/scene']);
  const types = h.events.map(e => e.item?.type || e.type);
  assert.deepEqual(types, ['function_call_output', 'message', 'message', 'response.create']);
  assert.match(h.events[1].item.content[0].text, /overhead/);
  assert.match(h.events[2].item.content[0].text, /wrist/);
  assert.match(h.events[2].item.content[0].text, /Upright Wrist view/);
  assert.doesNotMatch(h.events[2].item.content[0].text, /sideways/);
  assert.equal(h.events[1].item.content[1].type, 'input_image');
  assert.ok(!h.events[0].item.output.includes('base64'));
  assert.equal(h.events[3].response.tool_choice, 'none', 'no automatic image polling loop');
  assert.match(h.events[3].response.instructions, /without naming cameras/);
  assert.match(h.events[3].response.instructions, /Inspect both available views/);
  assert.match(h.events[3].response.instructions, /without.*mentioning your own gripper/);
  sceneCall(h);
  await setImmediate();
  assert.equal(h.requests.length, 1);
  assert.equal(h.events.filter(e => e.type === 'response.create').length, 1);
  assert.equal(h.context.realtimeTaskActive, false);
});

test('capture ending in an old conversation cannot inject images into the new one', async () => {
  const h = harness();
  let complete;
  h.context.fetch = async () => new Promise(resolve => { complete = resolve; });
  sceneCall(h);
  h.context.conversationGeneration += 1;
  complete({ ok: true, body: snapshot });
  await setImmediate();
  assert.equal(h.events.length, 0);
});

test('capture failure is returned and spoken, without claiming a robot task failed', async () => {
  const h = harness();
  h.context.fetch = async () => ({ ok: false, body: { detail: 'Kameras nicht aktiv' } });
  sceneCall(h);
  await setImmediate();
  assert.match(h.events[0].item.output, /Kameras nicht aktiv/);
  assert.equal(h.events.filter(e => e.type === 'response.create').length, 1);
  assert.equal(h.events.filter(e => e.item?.role === 'system').length, 0);
});

test('new speech waits for the scene, then one answer sees both images and speech', async () => {
  const h = harness();
  let complete;
  h.context.fetch = async () => new Promise(resolve => { complete = resolve; });
  sceneCall(h);
  h.deliver({ type: 'input_audio_buffer.speech_started' });
  h.deliver({ type: 'input_audio_buffer.committed', item_id: 'new-question' });
  assert.equal(h.events.length, 0);
  complete({ ok: true, body: snapshot });
  await setImmediate();
  assert.equal(h.events.at(-1).type, 'response.create');
  assert.equal(h.events.at(-1).response.tool_choice, 'auto');
  assert.equal(h.events.filter(e => e.type === 'response.create').length, 1);
});

function projectInfoCall(h, callId = 'info-1', argumentsText = '{}', completion = 'completed', name = 'get_project_info') {
  h.deliver({ type: 'response.created' });
  h.deliver({ type: 'response.done', response: { status: completion, output: [
    { type: 'function_call', name, call_id: callId, arguments: argumentsText },
  ] } });
}

test('creator lookup uses its own endpoint without an arm or technical-info request', async () => {
  const h = harness();
  h.context.conversationVoiceOnly = true;
  h.context.conversationMotionId = null;
  const info = { status: 'available', background: 'Eleni Kofekidou / BlackChila created the RoboTalk setup.' };
  h.context.fetch = async (url, opts) => {
    h.requests.push({ url, opts });
    return { ok: true, body: info };
  };
  projectInfoCall(h, 'creator-1', '{}', 'completed', 'get_creator_info');
  await setImmediate();
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, '/api/conversation/realtime/creator-info');
  assert.equal(h.requests[0].opts.headers['X-SO101-Conversation'], 'realtime-tool');
  assert.equal(h.requests[0].opts.body, undefined);
  assert.deepEqual(JSON.parse(h.events.find(e => e.item?.type === 'function_call_output').item.output), info);
  const replies = h.events.filter(e => e.type === 'response.create');
  assert.equal(replies.length, 1);
  assert.equal(replies[0].response.tool_choice, 'none');
  assert.match(replies[0].response.instructions, /SO-101 hardware/);
  assert.match(replies[0].response.instructions, /one or two short sentences/);
  assert.equal(h.context.realtimeTaskActive, false);
  projectInfoCall(h, 'creator-1', '{}', 'completed', 'get_creator_info');
  await setImmediate();
  assert.equal(h.requests.length, 1);
});

test('creator errors and forged arguments never become a motor request', async () => {
  for (const args of ['{}', '{"instruction":"move"}']) {
    const h = harness();
    h.context.fetch = async (url) => { h.requests.push({url}); return { ok: false, body: { detail: 'No notes' } }; };
    projectInfoCall(h, 'creator-error', args, 'completed', 'get_creator_info');
    await setImmediate();
    assert.equal(h.requests.length, args === '{}' ? 1 : 0);
    assert.ok(JSON.parse(h.events.find(e => e.item?.type === 'function_call_output').item.output).error);
    assert.equal(h.context.realtimeTaskActive, false);
    assert.equal(h.events.filter(e => e.item?.role === 'system').length, 0);
    assert.equal(h.events.filter(e => e.type === 'response.create').length, 1);
    assert.equal(h.events.at(-1).response.tool_choice, 'none');
  }
});

test('technical info works without an arm and returns one concise tool-free continuation', async () => {
  const h = harness();
  h.context.conversationVoiceOnly = true;
  h.context.conversationMotionId = null;
  const info = { status: 'ok', activeMode: 'realtime', overview: 'SO-101 uses a separate robot policy.' };
  h.context.fetch = async (url, opts) => {
    h.requests.push({ url, opts });
    return { ok: true, body: info };
  };
  projectInfoCall(h);
  await setImmediate();
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].url, '/api/conversation/realtime/project-info');
  assert.equal(h.requests[0].opts.method, 'POST');
  assert.equal(h.requests[0].opts.headers['X-SO101-Conversation'], 'realtime-tool');
  assert.equal(h.requests[0].opts.body, undefined);
  assert.ok(h.requests[0].opts.signal instanceof AbortSignal);
  const output = h.events.find(e => e.item?.type === 'function_call_output');
  assert.equal(output.item.call_id, 'info-1');
  assert.deepEqual(JSON.parse(output.item.output), info);
  const replies = h.events.filter(e => e.type === 'response.create');
  assert.equal(replies.length, 1);
  assert.equal(replies[0].response.tool_choice, 'none');
  assert.match(replies[0].response.instructions, /Do not recite the full background/);
  assert.match(replies[0].response.instructions, /Reuse this information/);
  assert.equal(h.context.realtimeTaskActive, false);
  assert.equal(h.events.filter(e => e.item?.role === 'system').length, 0);
  projectInfoCall(h);
  await setImmediate();
  assert.equal(h.requests.length, 1, 'duplicate call IDs do not retrieve again');
});

test('technical info errors stay read-only and invalid arguments never reach the backend', async () => {
  for (const argumentsText of ['{}', '{"instruction":"Move"}', 'null']) {
    const h = harness();
    h.context.fetch = async (url) => {
      h.requests.push({ url });
      return { ok: false, body: { detail: 'Information unavailable' } };
    };
    projectInfoCall(h, 'info-error', argumentsText);
    await setImmediate();
    assert.equal(h.requests.length, argumentsText === '{}' ? 1 : 0);
    assert.ok(JSON.parse(h.events.find(e => e.item?.type === 'function_call_output').item.output).error);
    assert.equal(h.events.filter(e => e.item?.role === 'system').length, 0);
    assert.equal(h.events.filter(e => e.type === 'response.create').length, 1);
    assert.equal(h.events.at(-1).response.tool_choice, 'none');
    assert.equal(h.context.realtimeTaskActive, false);
  }
});

test('technical info respects playback scheduling, connection limits and conversation lifetime', async () => {
  const playing = harness();
  playing.context.fetch = async () => ({ ok: true, body: { status: 'ok', background: 'Short setup facts.' } });
  playing.context.realtimeTaskFeedback.playbackStarted('announcement');
  projectInfoCall(playing);
  await setImmediate();
  assert.equal(playing.events.filter(e => e.type === 'response.create').length, 0);
  playing.context.realtimeTaskFeedback.playbackFinished('announcement');
  assert.equal(playing.events.filter(e => e.type === 'response.create').length, 1);

  const limited = harness();
  limited.context.realtimePeer.sctp.maxMessageSize = 500;
  limited.context.fetch = async () => ({ ok: true, body: { content: 'x'.repeat(2000) } });
  projectInfoCall(limited);
  await setImmediate();
  assert.match(limited.events[0].item.output, /message limit/);
  assert.ok(limited.events[0].item.output.length < 500);

  const stale = harness();
  let complete;
  stale.context.fetch = async () => new Promise(resolve => { complete = resolve; });
  projectInfoCall(stale);
  stale.context.conversationGeneration += 1;
  complete({ ok: true, body: { status: 'ok', content: 'Old call facts' } });
  await setImmediate();
  assert.equal(stale.events.length, 0);

  const cancelled = harness();
  projectInfoCall(cancelled, 'cancelled-info', '{}', 'cancelled');
  await setImmediate();
  assert.equal(cancelled.requests.length, 0);
});

test('partial views and transport limits are explicit; no oversized messages are sent', async () => {
  const h = harness();
  h.context.fetch = async () => ({ ok: true, body: { ...snapshot, status: 'partial', images: snapshot.images.slice(0, 1), unavailable: [{ camera: 'wrist', error: 'offline' }] } });
  sceneCall(h);
  await setImmediate();
  assert.match(h.events[0].item.output, /offline/);
  assert.equal(h.events.filter(e => e.item?.content?.some(c => c.type === 'input_image')).length, 1);
  const limited = harness();
  limited.context.realtimePeer.sctp.maxMessageSize = 100;
  limited.context.fetch = async () => ({ ok: true, body: snapshot });
  sceneCall(limited);
  await setImmediate();
  assert.match(limited.events[0].item.output, /message limit/);
  assert.equal(limited.events.filter(e => e.item?.content).length, 0);
});

test('playback events keep the greeting speaking and defer the next response until it drains', () => {
  const h = harness();
  h.context.realtimeTaskFeedback.greet();
  h.deliver({ type: 'response.created', response: { id: 'hello' } });
  h.deliver({ type: 'output_audio_buffer.started', response_id: 'hello' });
  h.deliver({ type: 'response.done', response: { id: 'hello', status: 'completed', output: [] } });
  assert.equal(h.context.realtimeSpeaking, true);
  h.deliver({ type: 'input_audio_buffer.committed', item_id: 'question' });
  assert.equal(h.events.filter(e => e.type === 'response.create').length, 1);
  h.deliver({ type: 'output_audio_buffer.stopped', response_id: 'hello' });
  assert.equal(h.context.realtimeSpeaking, false);
  assert.equal(h.events.filter(e => e.type === 'response.create').length, 2);
});

test('web lookup works in voice-only mode, deduplicates and resumes without motor tools', async () => {
  const h = harness();
  h.context.conversationVoiceOnly = true;
  h.context.conversationMotionId = null;
  const result = { type: 'response.done', response: { status: 'completed', output: [
    { type: 'function_call', name: 'search_web', call_id: 'web-1', arguments: '{"query":"Wetter Berlin"}' },
  ] } };
  h.deliver({ type: 'response.created' });
  h.deliver(result);
  await setImmediate();
  assert.deepEqual(h.requests, [{ search: 'Wetter Berlin' }]);
  assert.equal(h.context.realtimeTaskActive, false);
  assert.equal(h.events.filter(e => e.item?.call_id === 'web-1').length, 1);
  const continuation = h.events.find(e => e.type === 'response.create');
  assert.equal(continuation.response.tool_choice, 'none');
  assert.match(continuation.response.instructions, /untrusted/);
  h.deliver(result);
  await setImmediate();
  assert.equal(h.requests.length, 1);
});

test('web search errors return to the dialogue without ending the call or starting a robot task', async () => {
  const h = harness();
  h.context.realtimeWebSearch.search = async () => { throw Error('Suchkontingent erschöpft'); };
  h.deliver({ type: 'response.created' });
  h.deliver({ type: 'response.done', response: { status: 'completed', output: [
    { type: 'function_call', name: 'search_web', call_id: 'failed-search', arguments: '{"query":"Wetter"}' },
  ] } });
  await setImmediate();
  const output = h.events.find(e => e.item?.call_id === 'failed-search');
  assert.match(output.item.output, /Suchkontingent/);
  assert.equal(h.context.conversationActive, true);
  assert.equal(h.requests.length, 0);
  assert.equal(h.context.realtimeTaskActive, false);
  assert.equal(h.events.filter(e => e.type === 'response.create').length, 1);
});

test('late search result from an ended call cannot enter the next conversation', async () => {
  const h = harness();
  let finish;
  h.context.realtimeWebSearch.search = () => new Promise(resolve => { finish = resolve; });
  h.deliver({ type: 'response.created' });
  h.deliver({ type: 'response.done', response: { status: 'completed', output: [
    { type: 'function_call', name: 'search_web', call_id: 'late-search', arguments: '{"query":"Wetter"}' },
  ] } });
  h.context.conversationGeneration = 2;
  finish({ status: 'ok', answer: 'Old result' });
  await setImmediate();
  assert.equal(h.events.length, 0);
});
