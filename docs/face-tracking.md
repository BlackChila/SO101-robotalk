# Face tracking during robot conversation

ChatGPT Realtime, Local · Piper and Local · Qwen share the tracking controller. Local session
registration replaces the Realtime connection gate; see
[local Piper / Qwen conversation](local-piper-conversation.md). The lifecycle and motor
limits below apply to both modes.

Face tracking uses the local wrist-camera stream and a CPU YuNet detector. The
tracking calculation stays local and does not use ChatGPT to calculate servo
targets. Separately, the conversation scene tool can send requested camera
snapshots to OpenAI or LM Studio; see [privacy](configuration.md#openai-conversation). The
existing camera worker owns capture, and the conversation controller remains the
single motor owner. Tracking starts automatically once a new Realtime call has
completed positioning (and the intro, when enabled) and connected. A completed
robot reset can start it again. A finished task or manual stop alone does not.

## Prepare the detector

Detection runs in the camera worker environment, `environments/robot`, with
OpenCV 4.x and `cv2.FaceDetectorYN` available. The download helper only needs the
Python standard library. Install the small model explicitly:

```bash
python3 scripts/download_face_detector.py
```

The helper installs `models/face-tracking/face_detection_yunet_2023mar.onnx`, the
OpenCV 4.x-compatible export from the official [OpenCV Zoo](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet).
It verifies a size of 232589 bytes and SHA-256
`8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`.
There is no implicit network download during detection. A missing or invalid
model blocks tracking and appears in the UI with the installation command.

## Operator controls

Select **Conversation** and **ChatGPT Realtime**. Tracking starts once per new call
when positioning is complete, Realtime is connected, and cameras are ready.
Camera readiness is refreshed even when conversation settings are closed, including
when an already loaded MolmoAct2 camera worker is retained for the new call.
The ordinary conversation wrist preview uses a 4:3 crop, matching the other camera
tiles. Only the annotated tracking image uses the complete native 16:9 field of
view, rotated upright, and is displayed while tracking is active and conversation
settings are open. Closing settings hides the image without stopping tracking;
there is no separate tracking panel, preview button, or search checkbox.
Wrist Roll adds occasional small head-tilt gestures during fresh face tracking.

In **Conversation settings**, **Suchstart: rechts / links** selects and remembers
the initial base search direction for the next activation. Search is enabled by
default, sweeping at 16 degrees/s and reversing at the joint/search boundaries.
With continuous fresh no-face frames, the wrist starts looking upward after
0.35 seconds, moving up to 70 degrees at 4 degrees/s. The base sweep starts after
1 second. Finding a face immediately restores normal two-axis tracking.
Ending the conversation, leaving its view, or switching voice modes stops tracking.
Only a tab that activated tracking may automatically stop it. Other open robot
UI tabs can read status without disabling the active call. Browser tracking
commands are also checked against the backend's active tracking session.
Manipulation also disables gaze control; returning from a task does not re-enable it.
The image disappears when tracking stops. **Reset robot**, whether called
from settings or the Realtime `reset_robot` tool, also disables tracking and
moves directly to the final recorded intro pose without replay or greeting. Voice stays connected.
Once the reset completes positioning and confirms a measured hold, the current Realtime call
can start tracking again when its cameras are ready. Tracking stays off if the
conversation has ended or its view was left during the reset.

The backend remains authoritative for motion permission and cleanup. A UI error
or an unreachable status endpoint is not evidence that a motor hold was verified.
Check the explicit backend hold status when diagnosing a shutdown.

## Controller

Each detection consumes the latest timestamped camera frame rather than queuing
old images. The controller follows the selected face's image centre using two
proportional axes: base (`shoulder_pan`) for horizontal error and `wrist_flex`
for vertical error. Wrist travel allows 70 degrees upward (decreasing angle) and 50 degrees downward
from the activation pose. Base travel allows 95 degrees to either side of that
pose. Both ranges are clipped to calibrated joint limits. Controller status reports
when vertical centering reaches one of these limits.
Shoulder and elbow retain their held pose. With a freshly tracked face, Wrist Roll
occasionally tilts 8–20 degrees to either side, briefly holds, then returns to its
neutral pose. Gesture directions alternate, with random amplitudes and a
0.5–1.5 second pause between gestures, plus 0.3–0.8 seconds held at each tilt.
Targets stay relative to the same neutral pose, preventing cumulative roll. Smooth motion is
capped at 12 degrees/s. Calibration and a 2-degree measured lead constrain travel around the normal
talking pose. Camera loss, search, tracking stop and task handover
suspend the gesture; stop paths hold the measured pose. Speech
animation supplies only the gripper contribution to the composed motor target.

The existing direction measurements suggest positive base looks right and
positive wrist flex looks down. This must still be confirmed on the software-
rotated image with the restored Wrist Roll posture before autonomous tracking is
commissioned. The controller currently fixes both correction signs to positive.
Base and wrist face-following each have a 10.4 degrees/s maximum and 26 degrees/s²
acceleration, with gain 62.4 degrees/s per normalized image offset. These are
30% higher than the previous tracking settings.
Gains, dead zone, velocity/acceleration limits, target lead, freshness and search
bounds are explicit controller configuration, not model predictions. A lost face briefly holds; stale frames hold instead of triggering
blind searching. Joint boundaries limit both tracking and search.

During tracking, the controller positions the detected face centre at 90% of the
upright image width and 50% of its height. The horizontal target is offset toward the edge opposite the gripper. In the native 16:9
camera orientation, this corresponds to approximately 50% width and 10% height.
Both axes remain subject to the calibrated tracking envelope. The initial upward tilt raises the search elevation
by up to 70 degrees; the
following base sweep remains at that elevation and can still miss a person
outside the camera field of view. Multiple visible faces also do not establish which person is speaking. The
first version retains a selected face by geometric association.

## Staged physical commissioning

Software implementation and automated tests do not commission physical movement.
Do not restart an active motor-owning backend to deploy this feature. Follow
[scene setup](scene-setup.md), including exposure, framing and fresh-image checks,
and the repository's torque-preserving exit requirements before physical use.

1. For commissioning, use the backend preview API with gaze motion off. Inspect
   the upright annotated preview at the actual
   conversation distance and lighting. Check detection continuity and timestamps.
2. With an operator, fresh clearance and available cutoff, disable search through the backend API and
   verify the final horizontal/vertical correction signs in the restored wrist
   posture. Then evaluate small, speed-limited tracking corrections.
3. Verify face loss, stale frames, explicit stop, call termination and task
   handover. Required stops hold the measured position with torque enabled;
   uncertainty in verification must be reported immediately.
4. Only after tracking is satisfactory, supervise a search inside the tested
   joint/cable/workspace bounds. Evaluate speaking and gaze together and verify
   that a manipulation task clears gaze targets before acquiring control.

No physical deployment, backend restart or test motion is implied by installing
this implementation. Record fresh physical results separately from unit tests.
