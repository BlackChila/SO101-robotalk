# Speech interface: current modes and behavior

The RoboTalk homepage is the `Conversation` (Conversation) workspace. There is no
tab selector or separate push-to-talk control page.
For installation, use [the Linux guide](getting-started.md); the mode descriptions
below do not imply that models or hardware are already installed on a fresh clone.

## Conversation modes

The maintainer reports **ChatGPT Realtime and Local · Piper as working** on the
reference setup. **Local · Qwen** now shares Piper's conversation controller,
tool dispatch and image analysis, using Qwen3-TTS for speech. Hardware-free tests
cover this integration; live Qwen and physical acceptance remain to be verified.

| UI mode | Pipeline | Robot/task capabilities |
| --- | --- | --- |
| `ChatGPT Realtime` | Browser microphone/audio ↔ OpenAI Realtime | Explicit task dispatch/reset via tools, scene snapshots, web search; shared local motion/face tracking when commissioned |
| `Local · Qwen` | Qwen3-ASR → LM Studio tool/vision API → Qwen3-TTS CustomVoice | Same announced task/reset tools, scene snapshots and tracking as Piper; no web-search tool |
| `Local · Piper` | Qwen3-ASR → LM Studio tool/vision API → CPU Piper | Announced task/reset tools, scene snapshots, shared local motion/face tracking; no web-search tool |

Realtime is the initial selection. Without a server-side OpenAI key it reports
unavailable; choose an installed local mode explicitly. Local dialogue needs an
LM Studio server and a loaded compatible model. The reference model key is
`qwen/qwen3.8-27b`; configure your own server/model using
[the LM Studio guide](../environments/conversation/README.md).

Qwen offers nine CustomVoice speakers; the UI defaults to Dylan. Piper offers
Thorsten/Kerstin (German), Amy/Ryan (US English), and Alan/Jenny (UK English).
Local modes process one
utterance, generate a reply, and play it before listening again; streaming TTS
and spoken interruption are not implemented for those local paths.
Realtime uses its own WebRTC audio and semantic voice-activity handling.

The conversation settings include `Conversation language` (`German` / `English`)
directly below the voice-mode selector. The stored choice is fixed for each call
and controls the initial system prompt, first generated greeting, subsequent
responses and local ASR/TTS language. Piper's voice list is restricted to that
language; Qwen and Realtime keep their voice choices independent of language.
The initial greeting and tool continuations must not reintroduce a hardcoded
German instruction when English is selected. Existing speech API callers that
omit language retain their previous defaults. Backend changes require a restart;
an already running Qwen speech worker must also be replaced to use the new
synthesis parameter. English calls refuse an older backend before arm startup.

`look_at_scene` supplies fresh Overhead and Wrist snapshots to the speech model,
without the Insta360 side view. Only the language-model encoder rotates the Wrist
copy 90 degrees clockwise into portrait orientation. Shared capture buffers,
robot-policy inputs (including MolmoAct2), recordings and tracking processing
retain their existing orientation. Both Realtime and local conversation prompts
consider relevant details from both views while describing one natural scene,
without camera names or invented details. These are requested snapshots, not a
continuous video feed. Backend prompt changes require a new conversation after
restarting the backend; encoder changes require a newly started camera worker.

Piper is a fully local conversation and manipulation workflow when ASR, LM
Studio, Piper, and MolmoAct2 run locally. It does not require an OpenAI API key
or a cloud speech service. Initial downloads require network access; pointing
LM Studio at another machine sends dialogue/images to that configured host.

Both local modes maintain the same bounded tool-dialogue history in the backend.
The browser has no persistent chat panel. See
[the shared local protocol and lifecycle](local-piper-conversation.md) for its exact tool
handoff and stale-response protections.

## Voice-only versus connected-robot conversation

When the configured Follower serial device is absent, conversation starts
without intro, motor animation, or return movement. This does not bypass another
active controller or erase an unconfirmed-hold warning.

When that device is present, `Start conversation` can position the arm and replay
its active intro trajectory. Realtime connects during preparation, suppresses
recorded intro audio, and speaks a generated greeting. Local Qwen/Piper also mute
the recorded intro audio and generate their own greeting after positioning.
The standalone replay CLI still plays the bundled recording. During speech,
a bounded audio-level envelope animates the gripper. It follows loudness rather
than phoneme-aligned lip shapes; newer timing and physical behavior need their
own supervised validation.

Face tracking/search/head-tilt motion can start after positioning and a connected
Realtime, Piper or Qwen session with ready cameras. It yields to manipulation. Refer
to [face tracking](face-tracking.md) for limits and commissioning, and
[the intro guide](demo-intro.md) for robot-specific bundle requirements.

## Task and reset tools

A clear request in Realtime can call `execute_molmo_task` after a spoken
announcement, **without a second confirmation exchange**. Each local mode proposes a stored
tool call, plays its announcement, and then dispatches it through the backend.
Other ordinary dialogue does not submit a task. All modes require a prepared
MolmoAct2 runtime and the physical controller's gates; speaking with the robot
alone does not install those components.

`reset_robot` and the UI reset control stop/invalidate the task and restart the
motor controller through the positioning path to the recorded intro **end pose**.
They preserve the voice conversation and do not replay the intro or repeat the
previous task. `End conversation` stops tasks and returns toward the intro
**start pose**. `Stop return` interrupts that return into a measured hold.
Interrupted return/recovery reports must be checked before another operation.

Stop, faults, and disconnects must preserve a verified measured-position
**torque-on hold** unless the operator explicitly requests torque off. Follow
[AGENTS.md](../AGENTS.md) and [scene setup](scene-setup.md); support the arm before
releasing torque. Do not rely on a UI error or terminal exit as hold verification.

## Privacy and validation

Realtime sends audio and requested scene snapshots to OpenAI. Its web-search tool
sends a search query to the Responses API. Results are supplied to the model;
there is no separate source-results panel. Local modes send dialogue and any requested scene images to the configured
LM Studio server. See [configuration and privacy](configuration.md).

The original host recorded ASR/TTS and two-turn LM Studio checks on 2026-09-24.
A warm check measured approximately 0.39 seconds for ASR, 1.93 seconds for a 27B
reply, and 3.97 seconds for synthesis of a 4.7-second answer. These were local
measurements, not guaranteed latency or validation of today's combined runtime.
The maintainer currently reports working Realtime and Piper conversations;
the Qwen integration has hardware-free software validation. Live Qwen speech,
concurrent performance, tools, face tracking, audio/motor timing, recovery, and continuous policy behavior need
separate physical acceptance.
