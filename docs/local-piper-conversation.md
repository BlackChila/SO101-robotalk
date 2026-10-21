# Local robot conversation with Piper or Qwen TTS

Select **Conversation → Local · Piper** or **Local · Qwen**. Both modes use
Qwen3-ASR, the configured LM Studio tool/vision model, and one shared local
conversation controller. Piper supplies CPU speech; Qwen supplies CUDA
CustomVoice speech. No OpenAI service is used by these modes.

The Qwen integration is covered by hardware-free protocol/API tests. Live
Qwen speech, concurrent model performance and physical tasks still require
acceptance on the target installation.

## Capabilities

- `execute_molmo_task`: one short instruction to the existing MolmoAct2 runner.
  A new spoken instruction replaces the current instruction and invalidates old
  predicted actions. The application plays the model's announcement before
  dispatching the stored tool call.
- `reset_robot`: the existing stop, verified hold, and controller restart to the
  intro end pose. The conversation and loaded policy remain available. A reset
  does not automatically repeat the previous task.
- `look_at_scene`: fresh overhead/wrist snapshots from the shared camera worker.
  Images stay in the backend/LM Studio path; missing views are reported. There
  is no continuous LLM video stream, and old image payloads are removed from
  subsequent dialogue turns.
- Face tracking, search and head-tilt gestures use the existing local detector
  and conversation motor controller. They start after intro/positioning and a
  connected local session, yield to manipulation, and can resume after reset.
- Task status stays visible. When a run stops or fails, a tool-free model reply
  speaks the actual controller status at the next quiet opportunity. Stopping
  a run is not evidence that the physical task succeeded.
- The existing gripper speech animation, run-stop button, conversation end,
  return and torque-preserving cleanup remain in use.
- After an announced motor tool is dispatched, no second model reply can abort
  the task. The task status is shown immediately; its eventual outcome is
  reported separately. Camera tool replies still describe their observations.
- At call start, the local LLM generates SO-101's opening greeting in the
  selected conversation language, with tools disabled. The selected TTS speaks it once
  before the microphone starts listening. The greeting is part of conversation
  history, so the next answer follows naturally. The opening instruction is a
  user turn for compatibility with LM Studio model templates. Both Piper and
  Qwen TTS mute the recorded intro audio and generate a fresh model greeting
  after the intro movement and keep it in their shared tool-dialogue history.

Web search is deliberately not exposed in either local mode.

## Runtime requirements

Use the existing environment, model and voice installation. Configuration:

- `SO101_LM_STUDIO_URL`, default `http://172.17.0.1:1234`.
- `SO101_CONVERSATION_MODEL`, default `qwen/qwen3.8-27b`.
- For Piper: `.onnx` and matching `.onnx.json` files described in
  [the Piper environment](../environments/piper/README.md).
- For Qwen: the existing CustomVoice environment and weights described in
  [the Qwen TTS environment](../environments/tts/README.md).

The LM Studio runtime/model combination must support structured function calls
through `/v1/chat/completions`. Scene understanding also requires a compatible
vision model with working `image_url` input. The application does not substitute
another model or download one automatically. A text-only model is insufficient
for scene descriptions. Test the installed model's tool and vision behavior
before physical use; mock protocol tests do not establish model reliability.
Both local modes set `reasoning_effort` to `none`, including turns with
tools and camera images.

Set `Conversation language` to `German` or `English` before starting the call. This
choice controls recognition, dialogue, the opening greeting, tool announcements,
scene descriptions, task feedback and synthesis for both local modes. Piper
offers Thorsten/Kerstin for German and Amy/Ryan/Alan/Jenny for English; the UI
filters the voice list to the selected language. All nine Qwen CustomVoice
speakers remain selectable for either language. Selecting Qwen's Ryan does not
change the conversation language. Switching voices during a call applies to the
next reply; an in-flight reply finishes with its original voice. Speech remains turn-based: full transcription,
model response, then WAV playback. Continuous interruption and streaming TTS are
not implemented in this version.

Local preparation accepts the existing conversation camera worker and an idle,
loaded MolmoAct2 model. It does not open a second camera capture process. Optional
policy preload after connection reuses the existing hardware-free preload route;
failure leaves conversation available, and task dispatch can load the policy.
Concurrent dialogue/vision, ASR, Qwen TTS and MolmoAct2 latency must be measured
on the host.

## Protocol and lifecycle

`/api/conversation/local/start` registers a local dialogue against the held motor
session, or a voice-only session when there is no active arm. Requests require
`X-SO101-Conversation: local-conversation` and the existing local-origin policy.
Start requests select `engine: "piper"` (default) or `engine: "qwen"` and a
provider-compatible `voice`. The backend keeps this engine through cancellation;
it validates subsequent voice changes against that provider.

1. `/{session}/greet` generates the opening line without tools and records it
   in dialogue history. The browser speaks it before listening.
2. `/{session}/turn` generates text and validated tool proposals without motion.
3. The browser plays the announcement. Only after playback finishes does it
   submit `/{session}/tool`, identifying a stored call. It cannot supply or change
   the instruction at this stage.
4. The backend checks the current motor session and dispatches through the same
   task/reset operations used by Realtime. Repeated call IDs return the stored
   result; uncertain failures are not automatically retried.
5. `/{session}/continue` sends tool results and optional images to the model
   with tools disabled. Its reply is spoken through the selected TTS provider.
6. `/{session}/feedback` summarizes controller status with tools disabled.

History is bounded to eight complete turns. At most one motor operation and one
scene observation are dispatched per turn, with reset taking precedence.
Ending the call revokes the local session. Operator reset or run-stop cancels
pending dialogue and announcements, retaining completed history. Late model
responses cannot execute calls in the replacement session. Browser or network
failure still relies on the existing controller heartbeat and verified hold
cleanup; cancelling dialogue itself is not a physical stop.

## Validation and deployment

Run local protocol/API tests, face-tracking and Realtime regressions, and the UI
build. Tests use simulated controller/model responses and do not move hardware.
The API tests may require execution outside a restricted sandbox for async
thread wakeups.

Before using a rebuilt UI, deploy the matching backend while the robot is idle.
The UI checks `localTaskProtocol: 1` before starting either local conversation.
Qwen also requires `localTtsEngines` to include `qwen`, so a new UI cannot start
Qwen robot tools against an older backend.
No backend restart or physical trial is performed by building this feature.
Follow [scene setup](scene-setup.md) and the repository's verified torque-on hold
requirements for a supervised physical check. First validate model function
selection and image understanding without motion, then test announcement,
tracking/task handoff, follow-up instruction, reset, stop and conversation end.
