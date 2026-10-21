// Vision never owns motors. A Realtime call enables gaze after intro or a verified reset.
export function faceTrackingEligibility(context) {
  const visible = context.view === 'conversation' && ['realtime', 'piper', 'local'].includes(context.mode);
  const taskBusy = context.taskActive || ['loading', 'running', 'stopping'].includes(context.taskState);
  const ready = visible && context.cameraReady && !taskBusy && !context.returning && !context.stopping;
  return { visible, preview: ready,
    enable: Boolean(ready && context.connected && context.active && context.sessionId && !context.voiceOnly) };
}

export class FaceTrackingControls {
  constructor(panel, {
    // Browser APIs must not receive this controller as their `this` receiver.
    directionButton = null,
    storage = globalThis.localStorage,
    fetchImpl = (...args) => fetch(...args),
    setTimer = (...args) => setTimeout(...args),
    clearTimer = (...args) => clearTimeout(...args),
  } = {}) {
    this.panel = panel;
    this.directionButton = directionButton;
    this.storage = storage;
    this.searchDirection = 'right';
    try { if (storage?.getItem('so101-face-search-direction') === 'left') this.searchDirection = 'left'; } catch {}
    directionButton?.addEventListener('click', () => {
      this.searchDirection = this.searchDirection === 'right' ? 'left' : 'right';
      try { storage?.setItem('so101-face-search-direction', this.searchDirection); } catch {}
      this.render();
    });
    this.autoStartedSessions = new Set();
    this.resetReadySessionId = null;
    this.fetch = fetchImpl;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this.image = panel.querySelector('[data-face-image]');
    this.context = {};
    this.state = { mode: 'off' };
    // Polling shared status never grants this tab control of another call.
    this.ownedSessionId = null;
    this.ownsPreview = false;
    this.pending = false;
    this.pendingCount = 0;
    this.polling = false;
    this.timer = null;
    this.epoch = 0;
    this.queue = Promise.resolve();
    this.stopRequested = false;
  }

  setContext(context) {
    const before = faceTrackingEligibility(this.context);
    this.context = context;
    const eligibility = faceTrackingEligibility(context);
    if (!eligibility.visible && before.visible) {
      this.resetReadySessionId = null;
      this.epoch++;
      this.clearTimer(this.timer);
      this.timer = null;
      this.clearImage();
      if (this.state.mode !== 'off' || this.pending) void this.command('stop');
    } else if (this.ownedSessionId && this.state.mode === 'tracking' &&
        (!eligibility.enable || context.sessionId !== this.ownedSessionId) && !this.stopRequested) {
      void this.command('disable');
    }
    this.maybeAutoStart();
    this.render();
    if (eligibility.visible && !this.timer && !this.polling) this.schedule();
  }

  maybeAutoStart() {
    const id = this.context.sessionId;
    if (!this.context.introComplete || !id || this.autoStartedSessions.has(id)) return;
    const resetReady = this.resetReadySessionId === id;
    if (this.context.taskEverStarted && !resetReady) { this.autoStartedSessions.add(id); return; }
    if (!faceTrackingEligibility(this.context).enable || this.pending || this.stopRequested) return;
    this.autoStartedSessions.add(id);
    if (resetReady) this.resetReadySessionId = null;
    if (resetReady || this.ownedSessionId !== id || this.state.mode !== 'tracking') void this.command('enable');
  }

  rearmAfterReset(sessionId) {
    if (!sessionId || sessionId !== this.context.sessionId) return;
    this.resetReadySessionId = sessionId;
    this.autoStartedSessions.delete(sessionId);
    this.maybeAutoStart();
  }

  schedule() {
    if (!faceTrackingEligibility(this.context).visible || this.timer) return;
    this.timer = this.setTimer(() => { this.timer = null; void this.poll(); }, 500);
  }

  async poll() {
    if (this.polling || !faceTrackingEligibility(this.context).visible) return;
    this.polling = true;
    const epoch = this.epoch;
    try {
      if (this.pending) return;
      const result = await this.request('/status');
      if (epoch !== this.epoch || this.pending) return;
      this.state = result;
      this.localError = '';
      this.showImage();
    } catch (error) {
      if (epoch === this.epoch) { this.localError = `Status unavailable: ${error.message}`; this.clearImage(); }
    } finally {
      this.polling = false;
      this.render();
      this.schedule();
    }
  }

  async request(suffix = '', payload) {
    const response = await this.fetch(`/api/conversation/face-tracking${suffix}`, {
      cache: 'no-store', signal: AbortSignal.timeout(5000),
      ...(payload ? { method: 'POST', headers: { 'Content-Type': 'application/json',
        'x-so101-conversation': 'operator-face-tracking' }, body: JSON.stringify(payload) } : {}),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
    return result;
  }

  command(action) {
    const eligibility = faceTrackingEligibility(this.context);
    if (action === 'enable' && (!eligibility.enable || this.pending)) return Promise.resolve();
    if (action === 'preview' && (!eligibility.preview || this.pending)) return Promise.resolve();
    if (['enable', 'disable', 'stop'].includes(action) && this.context.sessionId) {
      this.autoStartedSessions.add(this.context.sessionId);
    }
    if (['disable', 'stop'].includes(action)) {
      this.resetReadySessionId = null;
      this.stopRequested = true;
    }
    const cleanup = ['disable', 'stop'].includes(action);
    // Capture ownership before the context can end or switch to a new call.
    const sessionId = cleanup ? this.ownedSessionId : this.context.sessionId;
    const ownsPreview = this.ownsPreview;
    const payload = { action, mode: 'realtime', search: true, searchDirection: this.searchDirection,
      ...(sessionId ? { sessionId } : {}) };
    this.pendingCount++;
    this.pending = true;
    this.epoch++;
    this.render();
    this.queue = this.queue.then(async () => {
      // A queued enable must not survive a call ending or switching views.
      if (action === 'enable' && (!faceTrackingEligibility(this.context).enable ||
          payload.sessionId !== this.context.sessionId || this.stopRequested)) return;
      // A tab with no local activation may observe tracking, but cannot stop it.
      if (cleanup && !sessionId && !ownsPreview) return;
      try {
        // Retain ownership while awaiting a reply so a stop also covers an
        // in-flight activation whose outcome has not reached the browser yet.
        if (action === 'enable') this.ownedSessionId = sessionId;
        if (['preview', 'enable'].includes(action)) this.ownsPreview = true;
        this.state = await this.request('', payload);
        if (action === 'stop') {
          this.ownedSessionId = null;
          this.ownsPreview = false;
        }
        this.localError = '';
        this.showImage();
      } catch (error) {
        this.localError = error.message;
        this.clearImage();
      }
    }).finally(() => {
      this.pendingCount--;
      this.pending = this.pendingCount > 0;
      if (['disable', 'stop'].includes(action)) this.stopRequested = false;
      this.maybeAutoStart();
      this.render();
    });
    return this.queue;
  }

  clearImage() { this.image.removeAttribute('src'); this.image.hidden = true; this.panel.hidden = true; }
  showImage() {
    const jpeg = this.state.vision?.preview?.jpeg;
    if (!this.context.settingsOpen || !jpeg || this.state.mode !== 'tracking' || !faceTrackingEligibility(this.context).enable || this.localError) return this.clearImage();
    this.image.src = `data:image/jpeg;base64,${jpeg}`;
    this.image.hidden = false;
    this.panel.hidden = false;
  }
  render() {
    this.showImage();
    if (this.directionButton) {
      this.directionButton.textContent = this.searchDirection === 'right' ? 'Search start: right →' : 'Search start: left ←';
      this.directionButton.setAttribute('aria-label', `Search starts ${this.searchDirection === 'right' ? 'right' : 'left'}; change direction`);
    }
  }
}
