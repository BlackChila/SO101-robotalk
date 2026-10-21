// Visual output meter only: no microphone access, fetches or motor commands.
export class PlaybackAmplitude {
  constructor() { this.level = 0; }

  sample(samples, dt) {
    let power = 0;
    for (const value of samples) power += value * value;
    const rms = Math.sqrt(power / Math.max(1, samples.length));
    // Fixed gain preserves the difference between quiet and loud speech.
    const target = Number.isFinite(rms) ? Math.sqrt(Math.min(1, Math.max(0, (rms - .003) * 6))) : 0;
    const tau = target > this.level ? .045 : .13;
    this.level += (target - this.level) * (1 - Math.exp(-Math.min(.1, Math.max(0, dt)) / tau));
    if (this.level < .002) this.level = 0;
    return this.level;
  }
}

export class SpeechWaveform {
  constructor(element, {
    requestFrame = callback => requestAnimationFrame(callback),
    cancelFrame = id => cancelAnimationFrame(id),
  } = {}) {
    Object.assign(this, { element, requestFrame, cancelFrame });
    this.cleanup = null;
  }

  stop() {
    this.cleanup?.();
    this.cleanup = null;
    this.element.style.setProperty('--speech-level', '0');
  }

  observeAnalyser(analyser, { context, player, isCurrent = () => true, disconnect = () => {} }) {
    this.stop();
    const envelope = new PlaybackAmplitude();
    const samples = new Float32Array(analyser.fftSize);
    const silence = new Float32Array(analyser.fftSize);
    let frame = null, previous = null, stopped = false;
    const stop = () => {
      if (stopped) return;
      stopped = true;
      if (frame !== null) this.cancelFrame(frame);
      disconnect();
      if (this.cleanup === stop) {
        this.cleanup = null;
        this.element.style.setProperty('--speech-level', '0');
      }
    };
    this.cleanup = stop;
    const tick = (time) => {
      if (stopped) return;
      if (!isCurrent() || context.state === 'closed') { stop(); return; }
      const dt = previous === null ? 1 / 60 : (time - previous) / 1000;
      previous = time;
      const audible = context.state === 'running' && !player.paused && !player.muted &&
        !player.ended && player.volume !== 0 && player.readyState >= 2;
      try {
        if (audible) analyser.getFloatTimeDomainData(samples);
        const level = envelope.sample(audible ? samples : silence, dt);
        this.element.style.setProperty('--speech-level', level.toFixed(4));
      } catch {
        // Optional visualization must never interrupt speech or controller cleanup.
        stop(); return;
      }
      frame = this.requestFrame(tick);
    };
    frame = this.requestFrame(tick);
    return stop;
  }

  observeStream(context, stream, options) {
    this.stop();
    const nodes = [];
    const disconnect = () => { for (const node of nodes) node.disconnect(); };
    try {
      const source = context.createMediaStreamSource(stream);
      nodes.push(source);
      const analyser = context.createAnalyser();
      nodes.push(analyser);
      analyser.fftSize = 512;
      // A silent sidechain keeps analysis running without playing the audio twice.
      const silent = context.createGain();
      nodes.push(silent);
      silent.gain.value = 0;
      source.connect(analyser);
      analyser.connect(silent);
      silent.connect(context.destination);
      return this.observeAnalyser(analyser, { ...options, context, disconnect });
    } catch {
      disconnect();
      return () => {};
    }
  }
}
