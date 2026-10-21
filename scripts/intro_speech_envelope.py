"""Read the intro's speech envelope without playing audio or opening hardware."""

import math
import subprocess
from pathlib import Path

import numpy as np


class IntroSpeechEnvelope:
    rate = 16000
    interval = 0.02

    def __init__(self, samples):
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or not samples.size or not np.isfinite(samples).all():
            raise ValueError("Invalid intro audio samples")
        self.duration = len(samples) / self.rate
        self.levels = []
        peak, level = 0.025, 0.0
        block = round(self.rate * self.interval)
        # Match ui/src/speech-envelope.js: adaptive gain, noise floor and
        # fast attack/release follow syllables rather than voice pitch.
        for offset in range(0, len(samples), block):
            window = samples[offset:offset + block]
            rms = float(np.sqrt(np.mean(window.astype(np.float64) ** 2)))
            peak = max(0.025, rms, peak * math.exp(-self.interval / 1.5))
            target = min(1.0, max(0.0, (rms - 0.004) / (peak - 0.004))) ** 1.2
            tau = 0.012 if target > level else 0.025
            level += (target - level) * (1 - math.exp(-self.interval / tau))
            if level < 0.005:
                level = 0.0
            self.levels.append(level)

    @classmethod
    def from_file(cls, path: Path):
        decoded = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
             "-vn", "-t", "30", "-ac", "1", "-ar", str(cls.rate),
             "-af", "highpass=f=120,lowpass=f=4000", "-f", "f32le", "pipe:1"],
            capture_output=True, check=True, timeout=15,
        )
        return cls(np.frombuffer(decoded.stdout, dtype="<f4"))

    def level_at(self, elapsed: float | None) -> float:
        if elapsed is None or not math.isfinite(elapsed) or not 0 <= elapsed < self.duration:
            return 0.0
        return self.levels[min(int(elapsed / self.interval), len(self.levels) - 1)]
