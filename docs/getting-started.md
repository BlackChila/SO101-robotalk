# Linux installation and downloads

This guide describes the reference Linux ARM64 / NVIDIA GB10 setup. It is not a
macOS port or a claim that a new machine has been tested. Commands are run in
**Bash, from the repository root**, unless stated otherwise. Read
[configuration and setup gaps](configuration.md) before physical use.

## Prerequisites

| Requirement | Purpose |
| --- | --- |
| Linux `aarch64` and NVIDIA GB10 with a working driver | Target of the pinned PyTorch CUDA 13.0 and NATTEN wheels |
| Python 3.12 available at `/usr/bin/python3.12` | ASR, robot/camera runtime, Qwen TTS, Piper, and optional dialogue download environment |
| Git and Bash | Checkout and `source scripts/*-env.sh` |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | Isolated Python environments and frozen dependency installation |
| [Node.js](https://nodejs.org/en/download) and npm | Vite UI build; use a supported LTS release satisfying the engine requirements in `ui/package-lock.json` |
| `ffmpeg`, `ffprobe`, `ffplay` | Browser audio conversion, intro timing/playback, and camera capture |
| `v4l2-ctl` (usually the `v4l-utils` package) | Linux USB camera controls |
| `arecord` (usually `alsa-utils`) | Optional command-line microphone recording |
| Browser with microphone access | Conversation on localhost |
| Internet access during installation | Dependencies, model weights, and any gated-model authentication |

The historical host used Python 3.12.3, driver 580.173.02, and `uv` 0.11.14.
Those are recorded observations, not a tested minimum-version matrix. There is
no complete memory/disk requirement benchmark for the combined app. Plan for
model sizes in the [README](../README.md), plus several large CUDA environments,
download caches, build output, and trial data. Only one policy worker is loaded
at a time, but speech and dialogue models may share the GPU.

On an Ubuntu/Debian host, audio/video utilities can be installed with:

```bash
sudo apt-get install git ffmpeg v4l-utils alsa-utils
```

Install Python, Node/npm, `uv`, and the NVIDIA driver using instructions appropriate
to your Linux host. Do not replace the working driver/CUDA stack just to follow
an example. Use `uname -m` and `nvidia-smi` to inspect the host before installing
the architecture-specific locks.

## Clone the repository

```bash
git clone https://github.com/BlackChila/SO101-robotalk.git
cd SO101-robotalk
```

The source is small compared with the separate model downloads. No model weights,
virtual environments, local calibration files, or third-party source checkouts
are included. There is no root `requirements.txt` or shared root Python project.

## Install the ASR backend

The backend currently warms Qwen3-ASR at startup, even when you later choose
Realtime conversation. Install its environment and checkpoint first:

```bash
UV_CACHE_DIR="$PWD/.cache/uv" uv sync --project environments/asr --frozen --python /usr/bin/python3.12
HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 HF_HUB_DISABLE_TELEMETRY=1 \
  HF_XET_CACHE="$PWD/.cache/hf-xet" \
  environments/asr/.venv/bin/python scripts/download_asr.py
```

The script downloads [Qwen3-ASR-1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)
at its pinned revision, selects ten files, and writes the model manifest. Weights
go to `models/asr/qwen3-asr-1.7b/` (~4.70 GB). The activation script enables
offline loading, so use the explicit online variables above for downloads.

To check transcription without robot commands, supply an existing audio file:

```bash
source scripts/asr-env.sh
python scripts/asr_transcribe.py --audio /absolute/path/to/your/audio.wav
```

It should print JSON with `language` and `text`; this uses the GPU and reads the
audio but does not open the motor controller. For CLI microphone recording and
historical ASR results, see [the ASR environment](../environments/asr/README.md).

## Build and start the app

```bash
npm --prefix ui ci
npm --prefix ui run build
source scripts/asr-env.sh
python -u scripts/asr_web.py
```

Open [http://127.0.0.1:8765/](http://127.0.0.1:8765/) on the Linux host. Check
[the status endpoint](http://127.0.0.1:8765/api/status) if startup seems slow:
`asrLoading` should eventually become `asrReady`. If the UI is missing, confirm
that `ui/dist/` was built. The homepage opens the conversation workspace directly. A missing optional
model should be reported as unavailable.

Building and starting the server do not initiate arm movement. With the configured
Follower connected, conversation and other explicit controls can initiate motion;
finish hardware commissioning before using them. See [the UI guide](../ui/README.md).

Keep one backend instance running. If 8765 is occupied, use the existing instance
or deliberately start another with `python -u scripts/asr_web.py --port 8766`
and open its built page on 8766. A second backend has independent workers and
can compete for GPU or hardware resources. The Vite development proxy always
points at 8765 unless its configuration is changed.

For a server without an arm, `Ctrl+C` stops the backend. During physical use,
stop the task/conversation first, inspect the verified motor-hold status, and
follow the explicit torque/arm-support procedure before shutting down. A terminal
exit alone does not prove that the arm is safe or torque is off.

## Optional: shared robot and camera runtime

Cameras and the robot controllers use an isolated LeRobot runtime. Install it
for camera previews and physical robot features; policy weights are not needed
for this environment:

```bash
python3.12 -m venv environments/robot/.venv
environments/robot/.venv/bin/python -m pip install -r environments/robot/requirements.txt
```

See [the robot runtime](../environments/robot/README.md). Its dependencies are
separate from ASR, dialogue, TTS and the optional MolmoAct2 policy. Complete the
[scene checks](scene-setup.md) and hardware commissioning before movement.
Some shared low-level helpers retain historical `flux3_` filenames; this does
not enable the removed FLUX policy.

## Optional: MolmoAct2 policy

This repository currently **does not contain a reproducible fresh-install
environment for MolmoAct2**. The reference setup links an existing external
LeRobot/MolmoAct2 environment and two model directories. See
[the adapter guide](../environments/molmoact2/README.md) for required paths,
checkpoint revisions, and a sample-only check. Do not copy someone else's
virtual environment or substitute an unrelated environment without checking compatibility.

This gap affects conversational robot tasks too: installing Realtime or Piper
does not install MolmoAct2. A tested standalone installer/lock is future work
requiring validation on the Linux host.

## Optional: conversation modes

The maintainer reports Realtime and the fully local Piper workflow as working
on the reference setup. `Lokal · Qwen` now shares Piper's tool/vision controller
with Qwen3-TTS speech. Live Qwen and physical acceptance remain unverified.

| Mode | Additional setup |
| --- | --- |
| ChatGPT Realtime | OpenAI API key; active model/API access and internet; local robot/camera runtime for robot features |
| Lokal · Qwen | LM Studio tool/vision model, Qwen3-TTS environment/weights, ASR already installed |
| Lokal · Piper | LM Studio + dialogue model, Piper environment/voices, ASR already installed |

For OpenAI, copy `.env.example` to `.env` **if you do not already have one**, then
fill in the key locally. An exported `OPENAI_API_KEY` also works. See
[configuration and privacy](configuration.md#openai-conversation).

For local dialogue, install [LM Studio](https://lmstudio.ai/download) on the
Linux host, download/load your chosen model, and enable its API server. The
reference model is `qwen/qwen3.8-27b` with `Q4_K_M` quantization. Consult
[the dialogue setup guide](../environments/conversation/README.md), including
the shared tool/vision API requirements for both local modes.
Export `SO101_LM_STUDIO_URL` to match your server before starting the backend;
the code's default `172.17.0.1:1234` is specific to the original host.

Install [Piper](../environments/piper/README.md) or
[Qwen TTS](../environments/tts/README.md) for the selected local voice mode.
For face tracking, [install YuNet](face-tracking.md#prepare-the-detector) separately.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `uv sync` cannot select a wheel | Confirm Linux ARM64, Python 3.12, the pinned package sources, and driver compatibility; do not rewrite locks on macOS |
| Model missing or offline-loading error | Run the relevant download with online flags; confirm local paths; don't assume a clone contains weights |
| ASR never becomes ready | Read backend logs; confirm the ASR checkpoint, CUDA, and available memory |
| Browser microphone unavailable | Allow microphone access and use localhost; check the browser/OS microphone permissions |
| Cameras unavailable | Install the robot/camera environment and `ffmpeg`/`v4l2-ctl`; verify by-id paths, permissions, and exclusive camera ownership |
| Local dialogue unavailable | Check LM Studio's model key, API server, URL, optional bearer token, and selected TTS installation |
| Realtime unavailable | Check the server-side key, API/model access, network, and any error shown; never post the key in a bug report |
| Robot reset or intro refused | Read the calibration/device/hash checks; do not bypass them or reuse the reference pose on another robot |
| `Address already in use` | Check the existing backend; use a free port only deliberately |

No fresh Linux install or hardware run was performed during the publication
documentation review. The [publication checklist](publishing-checklist.md)
includes the required clean-install and physical acceptance work.
