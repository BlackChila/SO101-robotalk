# Qwen3-ASR-1.7B transcription

This is an isolated local speech-to-text environment. Transcription does not
load TTS, MolmoAct2, or the SO-101 motor controller. The full UI has separate controls that can start physical controllers after
their gates pass. See [the Linux setup guide](../../docs/getting-started.md)
for the complete app.

From the repository root, install and download with:

```bash
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --project environments/asr --frozen --python /usr/bin/python3.12
HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 HF_HUB_DISABLE_TELEMETRY=1 \
  HF_XET_CACHE="$PWD/.cache/hf-xet" \
  environments/asr/.venv/bin/python scripts/download_asr.py
```

Then transcribe an existing file:

```bash
source scripts/asr-env.sh
python scripts/asr_transcribe.py --audio /absolute/path/to/audio.wav
```

To record a short sample deliberately from the default ALSA microphone:

```bash
source scripts/asr-env.sh
python scripts/asr_transcribe.py --record-seconds 5 --alsa-device plughw:CARD=Pro,DEV=0
```

To keep the model in memory and record repeated five-second segments after
pressing Enter:

```bash
source scripts/asr-env.sh
python scripts/asr_transcribe.py --listen --alsa-device plughw:CARD=Pro,DEV=0
```

For browser push-to-talk, build the UI once and start the local-only API:

```bash
cd ui && npm ci && npm run build && cd ..
source scripts/asr-env.sh
python scripts/asr_web.py
```

Open `http://127.0.0.1:8765/` on this host. Hold the microphone button to
record and release it to transcribe. The browser requests microphone access;
audio is uploaded only to the local API and deleted after transcription. The
server loads Qwen3-ASR in the background at startup (about 26 seconds in one
local check); the UI displays the loading state and enables push-to-talk only
when the model is ready. Later requests reuse the model. Transcription itself sends no motor command. In the full `Steuerung` UI,
push-to-talk also dispatches the recognized instruction to a loaded policy when
the camera and start-position gates pass; that can start a continuous physical
run. The explicit `Roboter zurücksetzen` button invokes the separate shared robot-runtime
motor holder. The reference pose currently records
`automatic_travel_validated=true` and `ui_reset_scope=any_calibrated_start`,
following original-robot commissioning. These settings do not validate another
robot. Stop/disconnect preserves a verified measured-position torque-on hold;
only explicit torque-off releases it. Read [the UI guide](../../ui/README.md)
and [hardware configuration](../../docs/configuration.md#robot-and-camera-configuration)
before using any physical control.

The output is JSON with `language` and `text`. Each microphone capture is a
temporary WAV removed when transcription finishes. The Razer Seiren V2 Pro was
visible as `plughw:CARD=Pro,DEV=0` on this host on 2026-09-24; recheck the
device name if it changes. `--language Auto` enables language detection; the
default forces German. No transcription triggers robot motion.

The runtime is pinned in `pyproject.toml` and `uv.lock`; the official checkpoint
is stored at `models/asr/qwen3-asr-1.7b/`. Its exact revision and file hashes
are recorded in `model-manifest.json` after download.

## Validation on 2026-09-24

- Python 3.12.3, `qwen-asr==0.0.6`, `torch==2.11.0+cu130`; CUDA was available
  to the isolated process on the NVIDIA GB10 host.
- Pinned model revision: `7278e1e70fe206f11671096ffdd38061171dd6e5`.
  Ten required files were downloaded and SHA-256 hashed.
- Local offline inference on a public 7.5-second German CustomVoice recording
  from [mana](https://mana.how/stimmen/) returned: `Hallo, ich bin eine der
  Stimmen des Vereins Mana. So klinge ich, wenn ich einen Text ruhig und
  deutlich vorlese.` The source sentence uses lowercase `mana`; no other words
  differed.
- A one-second capture from the Razer microphone produced 16 kHz mono WAV;
  that temporary file was deleted. No spoken microphone command was tested.
- The browser API accepted a WebM/Opus version of the same German voice sample,
  converted it locally to WAV, and returned the same transcript with Qwen.
  A live browser microphone recording still needs an operator voice check.

Source: [Qwen3-ASR official repository](https://github.com/QwenLM/Qwen3-ASR).
