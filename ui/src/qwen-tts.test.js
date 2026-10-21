import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const main = readFileSync(new URL('./main.js', import.meta.url), 'utf8');

for (const [mode, engine, voice] of [['local', 'qwen', 'Dylan'], ['piper', 'piper', 'Amy']]) {
  test(`${mode} connects the selected speech provider to the shared dialogue adapter`, () => {
    let options;
    const context = vm.createContext({
      conversationMode: mode, conversationSpeakerValue: () => voice, conversationLanguage: 'English',
      LocalRobotConversation: class { constructor(value) { options = value; } },
    });
    vm.runInContext(main.slice(main.indexOf('const localConversation ='),
      main.indexOf('\nconst conversationCall =')), context);
    assert.equal(options.engine(), engine);
    assert.equal(options.voice(), voice);
    assert.equal(options.language(), 'English');
  });

  test(`${mode} synthesis preserves the voice captured before a mid-reply speaker change`, async () => {
    const requests = [];
    let attached = 0, stopped = 0;
    const context = vm.createContext({
      conversationMode: mode, conversationSpeakerValue: () => 'Ryan', conversationLanguage: 'English',
      conversationAudio: null, conversationMotionId: null,
      conversationWaveform: { observeAnalyser(analyser, options) {
        attached++;
        assert.equal(options.isCurrent(), true);
        assert.equal(options.context, context.conversationAudioContext);
        return () => { stopped++; };
      } },
      conversationAudioContext: {
        createAnalyser: () => ({ connect() {}, disconnect() {} }),
        createMediaElementSource: () => ({ connect() {}, disconnect() {} }),
      },
      fetch: async (url, options) => {
        requests.push({ url, body: JSON.parse(options.body) });
        return { ok: true, blob: async () => ({}) };
      },
      URL: { createObjectURL: () => 'blob:test', revokeObjectURL() {} },
      Audio: class {
        listeners = {};
        addEventListener(event, callback) { this.listeners[event] = callback; }
        async play() { this.listeners.ended(); }
      },
      setInterval: () => 1, clearInterval() {},
    });
    vm.runInContext(main.slice(main.indexOf('async function speakConversation('),
      main.indexOf('\nfunction stopRealtimeSession(')), context);
    await context.speakConversation('Hallo!', new AbortController().signal, voice);
    assert.equal(requests[0].url, '/api/conversation/speak');
    assert.equal(requests[0].body.engine, engine);
    assert.equal(requests[0].body.language, 'English');
    assert.equal(engine === 'qwen' ? requests[0].body.speaker : requests[0].body.voice, voice);
    assert.equal(context.conversationAudio, null);
    assert.equal(attached, 1);
    assert.equal(stopped, 1);
  });
}
