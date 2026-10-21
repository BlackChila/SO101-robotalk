# Scene setup for SO101 RoboTalk

Before the first robot movement in a session, inspect the current camera images,
lighting, robot calibration and clear workspace. This guide does not authorize
movement on an uncommissioned arm. Follow [AGENTS.md](../AGENTS.md).

## Before physical operation

1. Remove unrelated objects from the robot's reachable area and keep a physical
   power cutoff available. The reference pose and intro are robot-specific.
2. Open conversation settings and inspect fresh Overhead, Insta360 X5 and Wrist
   previews. The shared UI worker owns the cameras; do not run a second capture
   process while it is active.
3. Verify that the actual object, destination, gripper and relevant arm links are
   visible in the views used by the task. Check exposure and focus after any
   lighting or mounting change. Dark or clipped frames must be corrected before
   a run, and a visible image alone is not proof of model readiness.
4. For manipulation, verify fresh Overhead/X5 frames and the MolmoAct2 runtime.
   For face tracking, verify the upright Wrist image and detector status. A
   camera-only conversation preview is not a physical-inference readiness check.

Device paths, profile baselines and input slots are defined in
[`scripts/camera_profiles.py`](../scripts/camera_profiles.py). Use stable
`/dev/v4l/by-id/` identities rather than volatile `/dev/videoN` numbers. Native
camera settings and each profile's limits still apply. The historical helper
`scripts/flux3_scene_setup.py` supplies shared camera/control definitions; its
name does not imply FLUX policy support.

## Camera roles

| View | Device on the reference setup | Use |
| --- | --- | --- |
| Overhead | Innomaker U20CAM 720P | MolmoAct2 `cam0`, scene tool and operator preview |
| Insta360 X5 | Insta360 X5 USB panorama | Projected MolmoAct2 `cam1` and operator preview |
| Wrist | Innomaker U20CAM 1080P | Face tracking, scene tool and operator preview; excluded from MolmoAct2 input |

The conversation scene tool uses Overhead and Wrist snapshots. Its encoder
rotates a copy of the Wrist image clockwise; policy buffers and capture data are
unchanged. UI/tracking display uses an upright portrait view. A camera crop or
image size does not establish a match with the policy's training viewpoints.

## MolmoAct2 live camera setup

The fixed projection values and captured frames in this section describe the
external reference runner's 2026-09-26 framing experiment. The current UI uses
`camera_profiles.py` and `insta360_view.py`, with yaw/pitch/roll/zoom persisted in
ignored `config/insta360-view.local.json`. It also supports an explicitly labeled
single-view fallback. See [the current Molmo adapter](../environments/molmoact2/README.md)
and [UI controls](../ui/README.md); do not infer today's framing from old output
images or assume the external runner is included in this repository.

The separate live MolmoAct2 runner in `/home/dfin/projects/SO101` uses
Overhead as Kamera 1 (`cam0`) and Insta360 X5 as Kamera 2 (`cam1`) by default. The Wrist camera is not
opened for this pair. This project's UI additionally opens an optional, independent
15-fps Wrist preview in the conversation workspace beside the two policy views in a row of three equally sized,
smaller camera images. Its gear provides
brightness and exposure controls. Missing or stalled Wrist frames do not block
the policy pair; Wrist images are excluded from MolmoAct2 inference and capture
archives. The X5's 2880 x 1440 panorama is reprojected directly
to a focused 960 x 720 perspective of the robot, pot, and work surface. That
view is already 4:3, so the runner's center-crop step changes no X5 pixels;
the overhead 1280 x 720 image is cropped to 960 x 720. MolmoAct2's saved
processor then resizes each image to 378 x 378.

The MolmoAct2 X5 center view uses yaw 65 degrees, pitch 15 degrees, roll 55
degrees, and a 52-degree horizontal field of view (39 degrees vertical). This
local framing choice was checked against a fresh USB panorama on 2026-09-26
after the camera moved. It shows the robot arm, ball, pot, and work surface;
the roll compensates for the camera's rotated mounting so the table is level.
It is not a verified training-camera match.

Inspect the live UI worker's projected `cam1` frame after any later projection change.
In this project's UI, gear icons inside each camera image toggle settings
panels, initially closed. Each panel controls that physical camera's native
V4L2 brightness using its reported range. Apply verifies device readback and
saves the brightness by device identity in `config/camera-brightness.local.json`.
The same panel offers manual exposure when supported. Lower exposure reduces
captured light; native brightness changes the black level and cannot recover
clipped highlights. Exposure is shown in milliseconds, limited to the 30-fps
frame interval (33.3 ms), verified against device readback, and persisted in
`config/camera-exposure.local.json`. Reset chooses the current profile baseline.
Saved manual exposure overrides that baseline on subsequent starts. A failed
preview or save restores the previous hardware exposure. Camera adjustments
are refused during policy runs and physical camera leases.
The setting is restored after the profile's exposure/gain setup on camera start.
The Insta360-only controls inside its settings panel adjust
yaw (horizontal), pitch (vertical/tilt), and roll (rotation). Click
„Übernehmen“ to preview and save the direction in
`config/insta360-view.local.json`; subsequent UI camera starts use it. The same
panel has a 1–2× zoom slider: it narrows the 52° × 39° field of view by the
same factor in both directions, while the panorama capture remains 2880 × 1440
and the projected image remains 960 × 720 (4:3). This digital zoom does not
increase the X5's optical detail. „Standardwerte“
selects the original 65/15/55-degree direction for the next apply. The panel
is hidden when the X5 is absent or unused, including overhead-only fallback.
Changes are blocked while a physical run owns the camera stream.
The camera can emit
black frames immediately after opening, so the UI camera worker waits for a
visible frame and retries opening it before supplying a physical run. Before a later
physical MolmoAct2 run, inspect new Overhead and X5 frames for the
object, pot, gripper, and reachable area. The projection and crop are specific to the MolmoAct2 policy input. The speech UI
sends fresh Overhead/X5 images to the MolmoAct2 shadow worker; the physical
runner reads the same frames and combines them with live joint state.
For the bright 2026-09-26 scene, the MolmoAct2 UI worker sets the Overhead
camera to manual exposure 150, gain 10, and gamma 100 before opening it.
The X5 stays at brightness 0 because its work surface remains visible.


## Conversation camera previews without a policy

The conversation settings toggle shows and hides the available camera feeds
together with the settings panel. If there is no active policy camera profile, it starts the camera-only
`conversation` profile: Overhead, Insta360 X5, and Wrist each have an independent
optional stream. No policy weights, robot serial ports, or shared inference
frame server are opened. Missing cameras are omitted, with no duplicate fallback
images. The X5 uses the saved perspective; brightness/exposure controls keep their
per-device preferences. Model inference and capture reject this preview profile.
The existing physical-client and policy-run guards still prevent conflicting
camera changes.
