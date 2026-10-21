import test from 'node:test';
import assert from 'node:assert/strict';
import { conversationLanguage } from './conversation-language.js';
import { RealtimeTaskFeedback } from './realtime-task-feedback.js';
import { LocalRobotConversation } from './local-robot-conversation.js';

test('selected language controls the initial greeting and tool continuations', () => {
  for (const language of ['German', 'English']) {
    const events = [];
    const scheduler = new RealtimeTaskFeedback(event => events.push(event), () => {}, () => language);
    scheduler.greet();
    assert.equal(events.length, 1);
    const greeting = events[0].response;
    assert.equal(greeting.tool_choice, 'none');
    assert.match(greeting.instructions, new RegExp(`Conversation language: ${language}`));
    if (language === 'English') {
      assert.match(greeting.instructions, /Hello, I am SO-101/);
      assert.doesNotMatch(greeting.instructions, /ausschließlich auf Deutsch|Hallo, ich bin/);
    } else assert.match(greeting.instructions, /Hallo, ich bin SO-101/);
    scheduler.responseFinished();
    scheduler.sceneReady();
    assert.match(events[1].response.instructions, new RegExp(`Conversation language: ${language}`));
  }
  assert.equal(conversationLanguage('invalid'), 'German');
});

test('local session receives its selected language before asking for the greeting', async () => {
  const calls = [];
  const client = new LocalRobotConversation({
    language: () => 'English', voice: () => 'Dylan', engine: () => 'qwen', speak: async () => {},
    request: async (url, options) => {
      calls.push({ url, body: JSON.parse(options.body) });
      return { ok: true, json: async () => url.endsWith('/start') ? { sessionId: 'session' } : { reply: 'Hello!' } };
    },
  });
  await client.start(null);
  await client.greet(new AbortController().signal);
  assert.equal(calls[0].body.language, 'English');
  assert.ok(calls[1].url.endsWith('/session/greet'));
});
