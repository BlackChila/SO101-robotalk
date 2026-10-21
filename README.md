# SO101 RoboTalk — conversation with an SO-101 robot

RoboTalk is an experimental browser interface for spoken conversation with an
SO-101 robot. The conversation workspace is the homepage, with no tab selector.
It combines OpenAI Realtime or local speech, camera previews, face tracking,
teleoperation, and optional MolmoAct2 robot tasks. The interface uses German labels.

This repository continues the conversation functionality of
[2026-PG-robotalk](https://github.com/BlackChila/2026-PG-robotalk). The separate
control workspace and FLUX.3/Galaxea G0.5 experiments are omitted.

The reference system is **Linux ARM64 with an NVIDIA GB10 GPU** (DGX Spark / a
compatible GB10 workstation). The checked-in Python locks and CUDA wheels target
that system. macOS, Windows, CPU-only execution of the full app, and Linux x86-64
have not been validated.

**Project status:** a research prototype built around one local robot setup.
Some software and supervised physical checks are recorded, and the maintainer
reports successful MolmoAct2 pick-and-place trials. General task reliability
and all current motion paths have not been established. A fresh clone
does not include models, Python environments, robot calibration, or the external
MolmoAct2 installation. See [known setup gaps](docs/configuration.md#known-setup-gaps).

## What you can do

| Feature | What it uses |
| --- | --- |
| Cloud conversation | OpenAI Realtime; optional scene snapshots, web search, and MolmoAct2 task tools |
| Local conversation with Qwen speech | Qwen3-ASR → LM Studio tool/vision API → Qwen3-TTS CustomVoice; shared Piper vision and robot tools |
| Local conversation with Piper speech | Qwen3-ASR → LM Studio → CPU Piper; optional vision and robot tools |
| Technical background questions | On-demand `get_project_info` in all three conversation modes; compact, sourced [setup notes](docs/project-info.md) with the selected conversation configuration |
| Who built this setup? | Separate `get_creator_info` lookup for [Eleni Kofekidou / BlackChila](docs/creator-info.md), focused on recent relevant professional work and attribution limits |
| Robot interaction | Camera controls, Leader/Follower teleoperation, saved-pose positioning, speech gripper animation, and face tracking |

**Current conversation status, reported by the maintainer:** OpenAI Realtime
and `Lokal · Piper` are working on the reference setup. Piper provides a
**fully local workflow**: Qwen3-ASR transcribes speech, a locally hosted LM Studio
model generates replies and task calls, Piper speaks, and MolmoAct2 runs locally.
After downloading the required components, this mode needs no OpenAI key or
cloud conversation service. Use a local LM Studio endpoint for local processing.

`Lokal · Qwen` now uses the same local conversation controller and tool/vision
protocol as Piper, with Qwen3-TTS CustomVoice speech. Hardware-free tests cover
the integration; live Qwen voice quality, concurrent runtime performance and
physical manipulation still need acceptance on the target setup. See the
[shared local conversation guide](docs/local-piper-conversation.md).

Conversation can run without an arm when the configured Follower serial device is
absent. With that device present, starting a conversation can position the arm,
play an intro gesture, and enable further movement. Realtime, Piper and Qwen can
dispatch explicitly requested robot tasks; they are not voice-only modes on a
connected robot.

## What to download

Download only the components for the workflow you want. **Model weights are not
in Git.** Installation commands and upstream download links are in
[the Linux setup guide](docs/getting-started.md).

| Component | Needed for | Download size / location |
| --- | --- | --- |
| Qwen3-ASR-1.7B | Local transcription and the app's ASR startup | ~4.70 GB → `models/asr/qwen3-asr-1.7b/` |
| Shared robot/camera runtime | Cameras, torque, intro, tracking and teleoperation | `environments/robot/`; no FLUX policy weights |
| MolmoAct2 converted and original checkpoints | Molmo inference and conversational manipulation | Reference installation uses ~44 GB; external setup required → `models/molmoact2/{runtime,source}` |
| Qwen3-TTS CustomVoice | `Lokal · Qwen` speech | ~4.52 GB → `models/tts/qwen3-tts-1.7b-customvoice/` |
| Dialogue model in LM Studio | Both local conversation modes | Reference model: Qwen3.8-27B `Q4_K_M`; installed separately |
| Piper voice files | `Lokal · Piper` speech | `.onnx` and `.onnx.json` pairs → `models/tts/piper/` |
| OpenCV YuNet | Face tracking | 232,589 bytes → `models/face-tracking/` |

Sizes above come from the committed manifests or installation notes, exclude
dependencies and caches, and are not total disk or GPU-memory requirements.
Each model and voice has its own upstream license. MolmoAct2 is optional for
voice conversation; its runtime is required for manipulation tasks.

## Conversational robot tasks

Explicitly requested manipulation uses
[MolmoAct2 SO100_101](https://huggingface.co/allenai/MolmoAct2-SO100_101) through
its [LeRobot conversion](https://huggingface.co/lerobot/MolmoAct2-SO100_101-LeRobot).
The maintainer reports successful pick-and-place on the reference setup without
project-specific fine-tuning. This is an observed result, not a benchmark or a
guarantee for another robot, scene or task. The dialogue model chooses a tool;
the separate policy and motor controller produce and execute gated joint actions.

## Getting started on the reference Linux system

1. Install Git, Bash, Python 3.12, Node.js/npm, `uv`, and the Linux audio/video
   utilities listed in [prerequisites](docs/getting-started.md#prerequisites).
   Verify the NVIDIA driver and CUDA availability on the target host.
2. Clone the repository and follow [installation](docs/getting-started.md#clone-the-repository)
   to create the isolated ASR environment and download its checkpoint.
3. Add only the optional environments/models you need. Read
   [configuration](docs/configuration.md) before connecting robot hardware.
4. Build the UI and start the backend from the repository root in **Bash**:

```bash
npm --prefix ui ci
npm --prefix ui run build
source scripts/asr-env.sh
python -u scripts/asr_web.py
```

Open [http://127.0.0.1:8765/](http://127.0.0.1:8765/) on the same Linux host.
Allow microphone access. ASR warms in the background; the UI reports its readiness.
Keep the terminal open while using the app. For later starts, the activation and
backend commands are sufficient unless the UI or its dependencies changed.

`scripts/asr-env.sh` activates `environments/asr/.venv/bin/activate` and sets
the runtime's cache and offline-loading environment variables.

These commands assume installation is complete; they do not download weights.
The app binds to loopback by default. Do not expose the robot backend as a public
web service. Cloud conversation needs a separately configured OpenAI API key and
incurs API costs; local modes do not require that key.

## Before any robot movement

Read [scene setup](docs/scene-setup.md) and
[hardware configuration](docs/configuration.md#robot-and-camera-configuration).
The committed pose, calibration fingerprint, device paths, and intro trajectory
belong to the original robot. They are not calibration or a safe start pose for
another arm. New hardware needs its own calibrated and supervised setup.

- Starting the backend does not move the arm. Explicit positioning,
  torque, teleoperation, conversation, and task controls can do so.
- Inspect fresh cameras and commission your own intro/start-pose setup before
  starting a conversation with a connected arm. Settings expose robot reset,
  model unload, torque and teleoperation.
- `Model Run stoppen` stops the current MolmoAct2 task while preserving the
  conversation and loaded model. There is no reliable automatic task-success
  detector; supervise and stop the run.
- Software stops and disconnects are intended to hold the measured pose with
  torque enabled. Verify the reported hold. Only an explicit torque-off action
  should release it; support the arm first. Unconfirmed communication is not a
  confirmed hold. Keep a physical power cutoff available.

Offline tests and finite model outputs do not establish safe motion, collision
avoidance, or successful manipulation.

## Documentation

- [Linux installation and downloads](docs/getting-started.md)
- [Configuration, privacy, and setup gaps](docs/configuration.md)
- [UI controls and development](ui/README.md)
- [Speech modes and their current behavior](docs/speech-interface.md)
- [Camera and scene setup](docs/scene-setup.md)
- [Local robot conversation](docs/local-piper-conversation.md)
- [Face tracking](docs/face-tracking.md) and [intro recording/replay](docs/demo-intro.md)
- [Environment overview](environments/README.md)
- [Documentation index](docs/README.md)

## Repository layout

```text
assets/demo/     Recorded intro audio and gesture bundles
config/          Reference robot start pose and runtime limits
docs/            Conversation setup, behavior, and configuration guides
environments/    Independent Python projects, locks, and model manifests
scripts/         API server, speech/model workers, cameras, and robot controllers
tests/           Python software checks
ui/              Vite frontend and JavaScript tests
```

`models/`, `.cache/`, `outputs/`, `.venv` directories, and frontend build output
are local and ignored. Generated traces and images are not distributed in this repository.

## Contributing and licensing

See [CONTRIBUTING.md](CONTRIBUTING.md) for issue reports and validation expectations.
Please describe which Linux host, environment, checkpoint, and hardware you used;
keep software checks separate from physical results.

Original project code and documentation are licensed under
[Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
See [LICENSE](LICENSE) for the full terms and [NOTICE](NOTICE) for author and
project attribution. The license permits commercial use, modification, and
redistribution of this original material. When distributing it or derivatives,
retain the applicable license/attribution notices and mark modified files as
required by the license.

Suggested credit: **RoboTalk by BlackChila**, with a link to
[this repository](https://github.com/BlackChila/SO101-robotalk) and the license.

This license covers original contributions whose owners authorize these terms.
Third-party code, dependencies, model weights, and voices retain their own terms.
Bundled material in `assets/demo/` is excluded from this license
pending ownership and redistribution review; inclusion in Git grants no reuse
permission for those assets. See the [third-party inventory](docs/third-party-materials.md).
Apache-2.0 is compatible with Piper's GPLv3 licensing, but does not replace it:
a distributed combined worker/Piper program must also comply with GPL.
Model and voice restrictions still apply independently, including any upstream
noncommercial terms. See [the publication review](docs/publication-review.md#ownership-and-project-license).
The maintainer's
[publication checklist](docs/publishing-checklist.md) tracks licensing, asset
permissions, privacy review, and remaining release checks.
