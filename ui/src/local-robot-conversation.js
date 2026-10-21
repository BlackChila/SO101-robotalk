// Local dialogue proposes calls; only completed audible announcements release
// motor calls. The server owns arguments, history, images and duplicate protection.
export function piperVoiceLanguage(voice) {
  return ['Amy', 'Ryan', 'Alan', 'Jenny'].includes(voice) ? 'English' : 'German';
}

export class LocalRobotConversation {
  constructor({ request = (...args) => fetch(...args), speak, voice = () => 'Thorsten', engine = () => 'piper', language = () => null, onTool = () => {} }) {
    this.request = request;
    this.speak = speak;
    this.voice = voice;
    this.engine = engine;
    this.language = language;
    this.onTool = onTool;
    this.sessionId = null;
    this.epoch = 0;
  }

  async api(path, body, signal, method = 'POST') {
    const response = await this.request(`/api/conversation/local/${path}`, {
      method, headers: { 'Content-Type': 'application/json', 'X-SO101-Conversation': 'local-conversation' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: signal || AbortSignal.timeout(15_000),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
    return result;
  }

  async start(motionSessionId) {
    const epoch = ++this.epoch;
    const language = this.language();
    const result = await this.api('start', { motionSessionId, voice: this.voice(), engine: this.engine(),
      ...(language ? { language } : {}) });
    if (epoch !== this.epoch) {
      await this.api(result.sessionId, undefined, undefined, 'DELETE');
      return false;
    }
    this.sessionId = result.sessionId;
    return true;
  }

  async close() {
    this.epoch++;
    const id = this.sessionId;
    this.sessionId = null;
    if (id) await this.api(id, undefined, undefined, 'DELETE');
  }

  async cancelTurn() {
    this.epoch++;
    if (this.sessionId) await this.api(`${this.sessionId}/cancel`);
  }

  async feedback(signal) {
    const id = this.sessionId;
    const epoch = this.epoch;
    if (!id) return;
    const voice = this.voice();
    const result = await this.api(`${id}/feedback`, { voice }, signal);
    signal.throwIfAborted();
    if (id !== this.sessionId || epoch !== this.epoch) return;
    await this.speak(result.reply, signal, voice);
  }

  async greet(signal) {
    const id = this.sessionId;
    const epoch = this.epoch;
    if (!id) throw new DOMException('Conversation ended.', 'AbortError');
    const voice = this.voice();
    const result = await this.api(`${id}/greet`, { voice }, signal);
    signal.throwIfAborted();
    if (id !== this.sessionId || epoch !== this.epoch) throw new DOMException('Conversation ended.', 'AbortError');
    await this.speak(result.reply, signal, voice);
    signal.throwIfAborted();
    if (id !== this.sessionId || epoch !== this.epoch) throw new DOMException('Conversation ended.', 'AbortError');
  }

  async turn(text, signal) {
    const id = this.sessionId;
    const epoch = this.epoch;
    const current = () => {
      signal.throwIfAborted();
      if (!id || id !== this.sessionId || epoch !== this.epoch) throw new DOMException('Conversation ended.', 'AbortError');
    };
    current();
    const voice = this.voice();
    const plan = await this.api(`${id}/turn`, { text, voice }, signal);
    current();
    if (plan.reply) await this.speak(plan.reply, signal, voice);
    current();
    for (const call of plan.toolCalls || []) {
      const motor = ['execute_molmo_task', 'reset_robot'].includes(call.name);
      if (motor && !plan.reply?.trim()) throw new Error('The spoken announcement is missing.');
      this.onTool(call, null);
      let result;
      try {
        result = await this.api(`${id}/tool`, { callId: call.id, announced: motor }, signal);
      } catch (error) {
        this.onTool(call, { error: error.message });
        throw error;
      }
      current();
      this.onTool(call, result);
    }
    if (plan.toolCalls?.length) {
      const answer = await this.api(`${id}/continue`, undefined, signal);
      current();
      if (answer.reply) await this.speak(answer.reply, signal, voice);
      current();
    }
  }
}
