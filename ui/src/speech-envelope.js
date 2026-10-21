// Analyze speech rhythm (amplitude), not the hundreds-of-Hz voice pitch.
// The audio itself remains unfiltered; this graph is only the motion sidechain.
export class SpeechEnvelope {
  constructor() { this.peak = 0.025; this.level = 0; }

  sample(samples, dt = 0.025) {
    dt = Math.max(0, Math.min(0.1, dt));
    let power = 0;
    for (const value of samples) power += value * value;
    const rms = Math.sqrt(power / Math.max(1, samples.length));
    if (!Number.isFinite(rms)) { this.level = 0; return 0; }
    // Slow gain recovery keeps quiet syllables visible without flattening valleys.
    this.peak = Math.max(0.025, rms, this.peak * Math.exp(-dt / 1.5));
    const target = Math.min(1, Math.max(0, (rms - 0.004) / (this.peak - 0.004))) ** 1.2;
    const tau = target > this.level ? 0.012 : 0.025;
    this.level += (target - this.level) * (1 - Math.exp(-dt / tau));
    if (this.level < 0.005) this.level = 0;
    return this.level;
  }
}

export function createSpeechMeter(context, stream) {
  const source = context.createMediaStreamSource(stream);
  const highpass = context.createBiquadFilter();
  highpass.type = 'highpass';
  highpass.frequency.value = 120;
  const lowpass = context.createBiquadFilter();
  lowpass.type = 'lowpass';
  lowpass.frequency.value = 4000;
  const analyser = context.createAnalyser();
  analyser.fftSize = 512;
  const silent = context.createGain();
  silent.gain.value = 0;
  source.connect(highpass).connect(lowpass).connect(analyser).connect(silent).connect(context.destination);
  const samples = new Float32Array(analyser.fftSize);
  const envelope = new SpeechEnvelope();
  let previous = context.currentTime;
  return {
    read() {
      const now = context.currentTime;
      analyser.getFloatTimeDomainData(samples);
      const level = envelope.sample(samples, now - previous);
      previous = now;
      return context.state === 'running' ? level : 0;
    },
    disconnect() { for (const node of [source, highpass, lowpass, analyser, silent]) node.disconnect(); },
  };
}

// One bounded request at a time: never accumulate a queue of old mouth positions.
export function startSpeechLevelPump({ read, enabled, send, onError, interval = 25 }) {
  let stopped = false;
  let pending = false;
  const timer = setInterval(async () => {
    if (stopped || pending || !enabled()) return;
    pending = true;
    try { await send(read()); }
    catch (error) { if (!stopped) onError(error); }
    finally { pending = false; }
  }, interval);
  return () => { stopped = true; clearInterval(timer); };
}
