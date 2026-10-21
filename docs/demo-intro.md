# Replaceable demo intro

The current intro is a **test take for the original robot**. Its calibration
fingerprint and joint trajectory are not a safe preset for another arm. Prepare
your own calibration and validated recording before using it. All capture/replay
commands below are physical operations, including `--pause-at-start`; it moves
the Follower before pausing. Read [scene setup](scene-setup.md) and follow
[controller requirements](../AGENTS.md).

The CLI examples use the original host's separate SO101 Python environment,
which is not included in this repository. They describe that prepared Linux
installation, not a fresh-clone installer. Run them from this repository's root
only after confirming the compatible runtime and your hardware configuration.

The reference intro is a **test take**. The replay command reads the stable
[`active.json`](../assets/demo/intro/active.json) bundle. Its manifest points to
versioned audio and joint-trajectory files in the same directory. Changing the
active bundle does not require changing the replay code. The recorded timeline
includes movement before, during, and after the audio.

The physical replay first moves the Follower gradually to the take's recorded
start pose. That positioning is separate from the recorded timeline. It then
sends every saved joint goal at its recorded timestamp, starts the audio at the
recorded lead-in time, and leaves the Follower holding its measured final pose
with torque enabled. A complete take and matching audio/calibration hashes are
required before any movement.

From the repository root, replay the active intro with:

```bash
/home/dfin/projects/SO101/.venv/bin/python scripts/demo_intro_replay.py
```

To inspect the recorded start pose before playback, add `--pause-at-start`.
The Follower moves to that pose and holds torque while waiting for Enter;
`q` stops without playing the take.

To try another complete take without replacing the active one, pass its report:

```bash
/home/dfin/projects/SO101/.venv/bin/python scripts/demo_intro_replay.py \
  --take outputs/demo-intro/take-YYYYMMDDTHHMMSSZ.json
```

To record a new take, run:

```bash
/home/dfin/projects/SO101/.venv/bin/python scripts/demo_intro_capture.py \
  --audio /absolute/path/to/your/intro.mp3 --prepare-start --total-s 11
```

After the Follower reaches the Leader's current pose, it follows the Leader
continuously. Move the Leader and check the Follower before recording. Press
`r` in the capture terminal to arm the take; the next deliberate Leader
movement starts its timeline. Press `q` to stop without recording. This removes
the fixed countdown that was easy to miss when operating the arm away from the
terminal. Recording begins with that movement, audio begins four seconds later,
and the remaining time after the 2.586-second audio is about 4.4 seconds.

Use the complete `take-...json` report printed by that capture in the install
command:

```bash
PYTHONPATH=scripts /home/dfin/projects/SO101/.venv/bin/python \
  scripts/demo_intro_install.py --take outputs/demo-intro/take-YYYYMMDDTHHMMSSZ.json
```

The installer validates the complete take, copies its trajectory and audio into
the bundle, then switches `active.json` last. Older bundle files remain so an
in-progress replay is not invalidated. The source recording in `outputs/` also
remains intact. The current capture defaults to a four-second lead-in and an
eleven-second total recording; the full audio file must fit inside that period.

## Current conversation integration

With a commissioned and connected Follower, **Gespräch starten** positions it
for the active gesture. The recorded trajectory is still used, but the bundled
recorded audio is muted in the current conversation modes. Realtime speaks its
generated greeting while connected; local Qwen/Piper generate their own greeting
after positioning. The standalone replay CLI above still plays the audio.

During speech, the gripper follows a bounded audio-level envelope rather than
randomized opening targets. It animates loudness, not phoneme-aligned lip forms.
Arm joints otherwise hold the measured pose unless another permitted controller
behavior, such as tracking or a policy task, owns their targets. See
[the speech guide](speech-interface.md) for mode differences.

**Gespräch beenden** stops a running task, waits for its verified hold, and returns
toward the take's recorded **start pose**. **Rückfahrt stoppen** interrupts that
return into a measured torque-on hold. During initial positioning or intro,
ending the call cancels the current gesture through the controller cleanup path.
A fault or disconnect holds the measured pose; an unconfirmed hold must remain
visible. **Roboter zurücksetzen** instead restarts the controller to the take's
**end pose**, preserving the conversation without replaying the intro or greeting.

The operator confirmed an earlier intro replay in the UI. That does not validate
all newer speech animation, return/recovery, tracking, or task handoff behavior.
Check fresh software/controller status and supervise physical acceptance on the
actual setup; no hardware check was performed in the publication review.
