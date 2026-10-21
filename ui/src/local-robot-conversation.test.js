import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { LocalRobotConversation, piperVoiceLanguage } from './local-robot-conversation.js';

for (const engine of ['piper', 'qwen']) {
  describe(`${engine} conversation adapter`, () => {
    function harness() {
      const calls = [];
      const controller = new AbortController();
      let plan = { reply: 'I will pick up the ball.', toolCalls: [{ id: 'call', name: 'execute_molmo_task' }] };
      const client = new LocalRobotConversation({
        engine: () => engine,
        voice: () => engine === 'qwen' ? 'Dylan' : 'Thorsten',
        request: async (url, options) => {
          calls.push({ url, body: options.body && JSON.parse(options.body), method: options.method });
          const result = url.endsWith('/start') ? { sessionId: 'session' }
            : url.endsWith('/turn') ? plan
              : url.endsWith('/continue') ? { reply: 'The controller accepted the task.' } : { status: 'loading' };
          return { ok: true, json: async () => result };
        },
        speak: async text => calls.push({ spoken: text }),
        onTool: (call, result) => calls.push({ tool: call.name, result }),
      });
      return { client, calls, controller, setPlan: value => { plan = value; } };
    }

    test('motor request occurs only after announcement playback resolves', async () => {
      const h = harness();
      await h.client.start('motion');
      let finish;
      h.client.speak = text => { h.calls.push({ spoken: text }); return new Promise(resolve => { finish = resolve; }); };
      const pending = h.client.turn('Pick it up', h.controller.signal);
      await new Promise(resolve => setImmediate(resolve));
      assert.ok(!h.calls.some(c => c.url?.endsWith('/tool')));
      h.client.speak = async text => h.calls.push({ spoken: text });
      finish();
      await pending;
      assert.deepEqual(h.calls.find(c => c.url?.endsWith('/tool')).body, { callId: 'call', announced: true });
      assert.ok(h.calls.findIndex(c => c.spoken) < h.calls.findIndex(c => c.url?.endsWith('/tool')));
    });

    test('accepted MolmoAct call does not need another spoken model reply', async () => {
      const h = harness();
      await h.client.start('motion');
      const request = h.client.request;
      h.client.request = (url, options) => url.endsWith('/continue')
        ? Promise.resolve({ ok: true, json: async () => ({ reply: '', toolCalls: [] }) })
        : request(url, options);
      await h.client.turn('Pick it up', h.controller.signal);
      assert.equal(h.calls.filter(c => c.spoken).length, 1);
      assert.ok(h.calls.some(c => c.url?.endsWith('/tool')));
      assert.equal(h.client.sessionId, 'session');
    });

    test('cancel during speech and audio failure never dispatch a motor call', async () => {
      for (const failure of ['abort', 'audio']) {
        const h = harness();
        await h.client.start('motion');
        h.client.speak = async () => {
          if (failure === 'abort') h.controller.abort();
          else throw Error('audio unavailable');
        };
        await assert.rejects(h.client.turn('Pick it up', h.controller.signal));
        assert.ok(!h.calls.some(c => c.url?.endsWith('/tool')));
      }
    });

    test('camera tools work without speech or robot and always continue to the answer', async () => {
      const h = harness();
      await h.client.start(null);
      h.setPlan({ reply: '', toolCalls: [{ id: 'scene', name: 'look_at_scene' }] });
      await h.client.turn('What can you see?', h.controller.signal);
      assert.equal(h.calls.find(c => c.url?.endsWith('/tool')).body.announced, false);
      assert.equal(h.calls.filter(c => c.spoken).length, 1);
    });

    test('closed session rejects stale replies before speech or actions', async () => {
      const h = harness();
      await h.client.start('motion');
      const request = h.client.request;
      h.client.request = async (url, options) => {
        const response = await request(url, options);
        if (url.endsWith('/turn')) await h.client.close();
        return response;
      };
      await assert.rejects(h.client.turn('Pick it up', h.controller.signal), /Conversation ended/);
      assert.ok(!h.calls.some(c => c.spoken || c.url?.endsWith('/tool')));
    });

    test('manual reset invalidates an old local turn without closing the conversation', async () => {
      const h = harness();
      await h.client.start('motion');
      h.client.speak = async () => h.client.cancelTurn();
      await assert.rejects(h.client.turn('Pick it up', h.controller.signal), /Conversation ended/);
      assert.equal(h.client.sessionId, 'session');
      assert.ok(h.calls.some(c => c.url?.endsWith('/cancel')));
      assert.ok(!h.calls.some(c => c.url?.endsWith('/tool')));
    });

    test('a delayed start response is revoked when the user already ended', async () => {
      const h = harness();
      const request = h.client.request;
      h.client.request = async (url, options) => {
        const response = await request(url, options);
        if (url.endsWith('/start')) await h.client.close();
        return response;
      };
      assert.equal(await h.client.start('motion'), false);
      assert.equal(h.client.sessionId, null);
      assert.ok(h.calls.some(c => c.method === 'DELETE'));
    });

    test('status feedback speaks a server summary without tool dispatch', async () => {
      const h = harness();
      await h.client.start('motion');
      const request = h.client.request;
      h.client.request = async (url, options) => url.endsWith('/feedback')
        ? { ok: true, json: async () => ({ reply: 'The controller stopped; success is unverified.' }) }
        : request(url, options);
      await h.client.feedback(h.controller.signal);
      assert.ok(h.calls.some(c => c.spoken?.includes('unverified')));
      assert.ok(!h.calls.some(c => c.url?.endsWith('/tool')));
    });


    test('voice selection drives recognition language and changes on the next reply', async () => {
      for (const voice of ['Amy', 'Ryan', 'Alan', 'Jenny']) assert.equal(piperVoiceLanguage(voice), 'English');
      for (const voice of ['Thorsten', 'Kerstin']) assert.equal(piperVoiceLanguage(voice), 'German');
      const h = harness();
      const initialVoice = engine === 'qwen' ? 'Dylan' : 'Amy';
      const nextVoice = engine === 'qwen' ? 'Eric' : 'Kerstin';
      let selected = initialVoice;
      h.client.voice = () => selected;
      await h.client.start('motion');
      assert.equal(h.calls.find(c => c.url?.endsWith('/start')).body.voice, initialVoice);
      assert.equal(h.calls.find(c => c.url?.endsWith('/start')).body.engine, engine);
      h.client.speak = async (text, signal, voice) => {
        h.calls.push({ spoken: text, voice });
        selected = nextVoice; // A voice change during playback cannot mismatch the continuation.
      };
      await h.client.turn('Pick up the ball', h.controller.signal);
      assert.ok(h.calls.filter(c => c.spoken).every(c => c.voice === initialVoice));
      h.setPlan({ reply: 'Hallo!', toolCalls: [] });
      await h.client.turn('Hallo', h.controller.signal);
      assert.equal(h.calls.filter(c => c.url?.endsWith('/turn')).at(-1).body.voice, nextVoice);
      assert.equal(h.calls.filter(c => c.spoken).at(-1).voice, nextVoice);
    });

    test('the selected provider asks the model for its opening line and plays it before listening', async () => {
      const h = harness();
      const initialVoice = engine === 'qwen' ? 'Dylan' : 'Amy';
      const nextVoice = engine === 'qwen' ? 'Eric' : 'Kerstin';
      let selected = initialVoice;
      h.client.voice = () => selected;
      h.client.request = async (url, options) => {
        h.calls.push({ url, body: options.body && JSON.parse(options.body) });
        return { ok: true, json: async () => url.endsWith('/start')
          ? { sessionId: 'session' } : { reply: 'Hello, I am SO-101. What can I do for you?' } };
      };
      h.client.speak = async (text, signal, voice) => h.calls.push({ spoken: text, voice });
      await h.client.start('motion');
      await h.client.greet(h.controller.signal);
      assert.equal(h.calls.find(c => c.url?.endsWith('/greet')).body.voice, initialVoice);
      assert.deepEqual(h.calls.filter(c => c.spoken), [
        { spoken: 'Hello, I am SO-101. What can I do for you?', voice: initialVoice },
      ]);
      selected = nextVoice;
      assert.equal(h.calls.filter(c => c.spoken).length, 1);
    });

    test('ending the call during greeting generation prevents stale playback', async () => {
      const h = harness();
      await h.client.start('motion');
      const request = h.client.request;
      h.client.request = async (url, options) => {
        const response = await request(url, options);
        if (url.endsWith('/greet')) await h.client.close();
        return response;
      };
      await assert.rejects(h.client.greet(h.controller.signal), /Conversation ended/);
      assert.ok(!h.calls.some(c => c.spoken));
    });
  });
}
