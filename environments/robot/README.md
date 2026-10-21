# Shared SO-101 motor and camera runtime

This runtime is used by conversation gestures, intro replay, face tracking,
teleoperation, torque controls, and live camera workers. It does not install a
FLUX or Galaxea policy, checkpoint, NATTEN kernel, or model download tool.

On the Linux robot host, create a Python 3.12 virtual environment from the
repository root and install the pinned direct requirements:

```bash
python3.12 -m venv environments/robot/.venv
environments/robot/.venv/bin/python -m pip install -r environments/robot/requirements.txt
```

The LeRobot source revision is retained from the original shared runtime. This
requirements file is not a complete transitive lock or a claim that this reduced
runtime has been validated on physical hardware. Test it on your host before
commissioning motor commands. System tools include `v4l2-ctl` and `ffmpeg`; use
your own calibrated hardware configuration and follow [scene setup](../../docs/scene-setup.md).

Some shared modules still have a `flux3_` filename for compatibility with the
existing controller tests and configuration. They implement joint conversion,
measured-position holding, reset/torque checks, or camera setup; the FLUX policy
workers and runtime have been removed. Do not rename calibration/pose references
without updating and validating the installation's configuration.
