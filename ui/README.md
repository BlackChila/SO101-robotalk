# RoboTalk browser UI

A Vite frontend without a UI framework, served by `scripts/asr_web.py`.
The interface uses German labels. Start with [the project README](../README.md)
and [Linux installation](../docs/getting-started.md); the UI does not install
Python environments, models, or robot calibration.

## Build and serve

From the repository root:

```bash
npm --prefix ui ci
npm --prefix ui run build
source scripts/asr-env.sh
python -u scripts/asr_web.py
```

Open [http://127.0.0.1:8765/](http://127.0.0.1:8765/) on the Linux host.
The backend serves `ui/dist/` and `/api` on the same port. ASR warms in the
background; check the visible status or `/api/status`. Keep one backend running.
Rebuild after frontend changes and reload the page. Deploy backend changes only
when no active motor-owning session needs the old process.

For development, keep the backend on 8765 in one terminal and run this in another:

```bash
cd ui
npm ci
npm run dev -- --port 5173 --strictPort
```

Open [http://127.0.0.1:5173/](http://127.0.0.1:5173/). Vite proxies `/api`
to `127.0.0.1:8765`; both processes are required. A backend on another port can
serve its own built UI, but does not change Vite's proxy automatically.

## Conversation homepage

The app opens directly to **Gespräch**. There is no tab selector, control page,
policy selector, or push-to-talk control workspace. Old `?conversation` links
continue to reach the same page. FLUX.3 and Galaxea G0.5 are not included.

The settings gear keeps camera previews, voice/language selection, robot reset,
model run stop/unload, torque and teleoperation together. These are the original
conversation features. MolmoAct2 remains the optional manipulation model used by
conversation tools. Opening the page does not start a robot conversation or issue
an operator motion command.

`Modell entladen` releases only the policy worker, preserving cameras, voice and
the motor holder. Active runs, reset and lifecycle transitions block unloading.
`Model Run stoppen` stops an active MolmoAct2 task while preserving the loaded
model, voice and cameras. Local dialogue cancellation does not delay physical stop.

Teleoperation can start without cameras. Missing or stale images produce a warning
without blocking the dedicated Leader/Follower controller. Stopping must leave a
verified measured hold with torque enabled; only the explicit `Torque Aus` action
releases torque.

## Cameras

The shared camera worker runs in `environments/robot`. It owns USB capture and supplies previews/model observations;
do not start a second camera process alongside it.

- MolmoAct2 uses overhead (`cam0`) and an Insta360 X5 projection (`cam1`). If
  only one is available, the worker can duplicate it into both checkpoint slots;
  the UI labels that fallback. Its physical task quality is unvalidated.
- Conversation previews can run without a loaded policy and include the available
  observer views. Face tracking uses the wrist stream locally.

Camera gears expose brightness, supported exposure, and X5 projection/zoom
controls. X5 settings persist in ignored `config/insta360-view.local.json`.
Image controls are gated during policy execution. Reload cameras and inspect
fresh timestamps, exposure, and framing before movement; hiding previews does
not prove capture or a controller stopped. See [scene setup](../docs/scene-setup.md).

## Conversation interface

The approved Graphit × Cybergrün layout uses a side inspector on desktop and
stacks settings below the workspace on narrow screens. The gear opens it; its
header button closes it. The green voice name directly in the heading opens the
native menu and retains wheel/keyboard interaction through `voice-picker.js`.
Only a dropdown indicator sits beside it; no helper tooltip is shown.
The former separate selection bar and previous/next buttons were removed. Realtime
selection locks still apply during a call. Camera settings retain their separate
apply/default actions, and the rotated tracking preview keeps its natural upright
aspect ratio. The three views are Overhead, Insta360 and Wrist-Kamera, with equal
image-frame heights and a narrower portrait Wrist column. During tracking, the
marked preview replaces the raw Wrist image in the same slot. The raw image is
rotated 90 degrees clockwise so Wrist stays upright even without tracking; the
already upright tracking image is not rotated again. The original Wrist
settings remain available; camera settings occupy the row below. Narrow screens
stack these views. Conversation
styling is scoped in `src/conversation-redesign.css`.

With settings closed, title, speech orb, call action and feedback form one
centered column. The empty task-status row is hidden until actual feedback is
available. Opening settings returns to the desktop workspace layout; no separate
conversation controls or session logic are created for the focused view.

With settings closed, the original soft green speech orb and its outer rings are
shown. With settings open, horizontal speech bars replace it, capped to the same
width as the call button (370px, shrinking with available space). Both views share
actual output amplitude via `src/speech-waveform.js`,
with a noise gate, fixed sensitivity and smoothed attack/release. Realtime uses
a silent analysis branch of the remote audio stream; Piper and Qwen share the
existing TTS player's analyser. The display also runs without a robot session,
settles to its resting size during silence/pause/mute/buffering, and cleans up on
stop or audio replacement. It does not send motor commands or alter the gripper
envelope. The original breathing animation indicates listening/thinking; speaking
uses the measured output amplitude. Reduced-motion settings keep the orb still.

The settings gear shows camera previews, voice mode, conversation language,
robot reset and model unload. Research/source panels and their placeholder text
are removed; Realtime search runs without a DOM host and passes its results to
the conversation model. Modes are `ChatGPT Realtime`, `Lokal · Qwen`,
and `Lokal · Piper`; see [the speech guide](../docs/speech-interface.md) for their
pipelines, tool capabilities, and privacy differences.

`Gesprächssprache` sits directly below the three voice modes. Its `Deutsch` /
`English` selection is stored locally, applies from the first generated greeting
and is locked during a call, return or session transition. Realtime receives the
language in both its initial system prompt and tool/greeting continuations.
Local dialogue, ASR and Qwen TTS use the same selection; Piper offers voices for
the selected language and remembers each language's voice separately. English
startup checks backend language support before starting the arm.

The maintainer reports Realtime and Piper as working. Piper runs fully locally
with a locally hosted LM Studio model and needs no OpenAI API key. The Qwen3-TTS
mode now uses the same local tool/vision controller as Piper. Its integration
is tested with mocked models/controllers; live Qwen speech and physical tasks
still need target-host acceptance.

With the configured Follower device absent, conversation is voice-only. With it
present, starting a conversation can position the arm, play its gesture, animate
the gripper, and enable face tracking or task tools. A Realtime task can dispatch
following an announcement without a second confirmation. Both local modes dispatch stored
tool calls after its spoken announcement. All modes need the MolmoAct2 installation
for manipulation and retain controller gates.

`Roboter zurücksetzen` moves to the intro **end pose** through a controller restart,
without restarting speech or replaying the intro. `Gespräch beenden` stops a task
and returns toward the intro **start pose**. During return, `Rückfahrt stoppen`
can interrupt into a measured hold. Recovery after an interrupted return checks
controller status; a visible button alone is not proof of a verified hold.
Only an explicit torque-off action releases torque.

## Development and evidence

Frontend tests use Node's built-in runner:

```bash
node --test ui/src/*.test.js
```

Visual tokens live in `src/theme.css`, with styling in the other CSS files.
Python API/controller tests live in `../tests/`; dependency/setup caveats are in
[CONTRIBUTING.md](../CONTRIBUTING.md).

Offline UI/API tests do not demonstrate CUDA inference for MolmoAct2 or
commission physical motion. Read [configuration](../docs/configuration.md),
[face-tracking acceptance](../docs/face-tracking.md#staged-physical-commissioning),
and [controller requirements](../AGENTS.md) before supervised hardware checks.
