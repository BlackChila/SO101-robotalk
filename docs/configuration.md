# Configuration, privacy, and setup gaps

All examples refer to the Linux reference system. Model locks, CUDA sources,
serial-device handling, and V4L2 capture remain Linux-specific.

## Environment variables

Set these in the backend's Bash process **before** starting the server:

| Variable | Current default / purpose |
| --- | --- |
| `OPENAI_API_KEY` | No default; optional OpenAI Realtime and Responses web search |
| `SO101_LM_STUDIO_URL` | `http://172.17.0.1:1234`; local dialogue API server |
| `SO101_CONVERSATION_MODEL` | `qwen/qwen3.8-27b`; LM Studio model key |
| `SO101_LM_STUDIO_TOKEN` | Optional LM Studio bearer token |
| `SO101_WEB_SEARCH_MODEL` | `gpt-4.1-mini`; Responses model for the Realtime search tool |

For an LM Studio server bound to localhost on the same host:

```bash
export SO101_LM_STUDIO_URL=http://127.0.0.1:1234
export SO101_CONVERSATION_MODEL=qwen/qwen3.8-27b
source scripts/asr-env.sh
python -u scripts/asr_web.py
```

Choose a model key actually installed in your LM Studio instance. The URL above
is an example, not a change to the checked-in default.

The root `.env` reader currently handles **only `OPENAI_API_KEY`**. Other variables
in this table must be exported into the process environment; adding them to `.env`
does not configure those adapters. Model activation scripts also set offline/cache
variables; explicitly override them for downloads as shown in the install guide.

## OpenAI conversation

If there is no existing `.env`, copy `.env.example` to `.env` and add the key
locally. Otherwise, edit the existing file without replacing its contents.
An exported nonempty `OPENAI_API_KEY` takes precedence. `.env` is ignored by Git.
Keep the standard key on the server; the browser receives a short-lived Realtime
session credential. Current code selects `gpt-realtime-2.1` in
[`scripts/realtime_voice.py`](../scripts/realtime_voice.py); availability is
subject to your account/API access, and there is no model-selection environment
variable for this Realtime setting.

Realtime sends microphone audio to OpenAI and receives spoken audio. Its
`look_at_scene` tool can send fresh camera snapshots when invoked, and `search_web`
sends the search query through the server to the OpenAI Responses API. These
services incur API charges. Do not include private information in prompts or
images unless you intend to send it to that service.

Local modes send audio to the local ASR backend and dialogue to the configured
LM Studio server. Both local modes' scene tool can send images to that server. A server on
another host is still a network destination. Model/voice installation downloads
also contact upstream hosts; runtime-local speech is not a promise of zero
network activity across every feature.

Local output and worker logs can contain prompts, transcripts, device details,
and controller reports. Review them before sharing, even though generated
`outputs/` and log files are ignored by Git.

## Robot and camera configuration

The runtime has original-host constants as well as configuration files. There
is currently no general configuration loader for arbitrary `*.local.json` files.
Their ignore patterns prevent accidental commits; creating a new file does not
automatically override a setting. The X5 projection is a specific exception:
`scripts/insta360_view.py` reads `config/insta360-view.local.json`, and the UI can
save yaw, pitch, roll, and zoom there.

| Setting | Current source | What another setup needs |
| --- | --- | --- |
| Follower calibration and reference pose | `scripts/flux3_start_pose.py`, `config/flux3_start_pose.json` | Own calibration file, fingerprint, start pose, and supervised commissioning |
| Follower serial path | Reference pose config; additional physical-runner constants | Verified stable `/dev/serial/by-id/` path and matching robot identity |
| Leader path and calibration | `scripts/demo_intro_capture.py`, `scripts/asr_web.py`, other teleoperation helpers | Own Leader calibration and stable device path |
| Overhead/wrist paths and exposure | `scripts/camera_profiles.py` | Verified `/dev/v4l/by-id/` cameras, supported controls, fresh framing checks |
| X5 camera path | `scripts/camera_profiles.py`, `scripts/flux3_scene_setup.py` | Verified device and a tested projection for its real placement |
| Intro trajectory and audio | `assets/demo/intro/active.json` and its referenced files | Matching own calibration and recorded/validated gesture |
| Molmo environment and checkpoints | `environments/molmoact2/.venv`, `models/molmoact2/{runtime,source}` | Compatible independently prepared environment and model directories |

The reference calibration path is
`/home/dfin/projects/SO101/calibration/robots/so_follower/follower_main.json`.
That file and the separate `SO101` checkout are **not included**. The reference
pose says `automatic_travel_validated=true`, but that flag describes the original
robot's commissioning. It must not be taken as approval for another robot's motion.
The intro likewise carries the original calibration fingerprint.

Replacing hardware paths, making calibration settings portable, or adding a
general configuration interface would be code/runtime changes. They have not
been performed as part of this documentation cleanup. Do not silently bypass
identity, bounds, or hash checks to make another arm run.

Before physical operation, follow [scene setup](scene-setup.md) and the
[controller rules](../AGENTS.md). Shared cameras and the Follower connection
need a single owner. Do not run standalone capture or motor scripts alongside
the UI's active owners. A stopped process or missing device is not evidence
of a verified motor hold.

## Known setup gaps

1. **Fresh-install validation:** the ASR lock includes FastAPI, Uvicorn, multipart
   support, and HTTPX through transitive dependencies. The API stack is not
   declared directly in the ASR project. This review has not tested a clean Linux
   install; explicitly declaring app dependencies would be a future maintenance
   improvement, not a demonstrated missing-package fix. No lock or dependency
   change has been made here.
2. **MolmoAct2 reproducibility:** there is no committed independent dependency
   lock/installer; existing links point to an external environment. The reference
   adapter guide describes what is required but is not a complete fresh installer.
3. **Robot portability:** calibration and device paths are embedded in multiple
   scripts, and the committed pose/intro belong to one setup. Public readers can
   inspect the project, but hardware operation on another setup needs additional
   configuration work and validation.
4. **Dialogue-model download reproducibility:** the GGUF download helper reuses
   `environments/conversation/model-manifest.json` if present; no manifest is
   currently committed there. On a fresh checkout it resolves the upstream
   revision at download time and writes a local manifest. Piper voice downloads
   also lack a project-level pinned voice manifest.
5. **Development environment:** no complete test dependency lock is provided.
   Existing tests do not commission hardware or prove policy success.
6. **Validation evidence:** dated notes refer to ignored `outputs/` files and an
   external SO101 experiment checkout. Those raw traces are unavailable in a
   fresh clone unless the maintainer separately publishes reviewed evidence.

These gaps can be documented without changing behavior. A fully reproducible
fresh install and easier support for other robots will require a separate,
tested Linux implementation pass.
