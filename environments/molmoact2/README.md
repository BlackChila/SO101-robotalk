# MolmoAct2 SO-101 adapter

This repository contains inference/session adapters, **not a complete fresh-install
MolmoAct2 environment**. The original Linux GB10 setup reused a separately prepared
LeRobot 0.6.1 / PyTorch CUDA environment at
`/home/dfin/projects/SO101/inference/molmoact2/.venv`. Its local links and model
weights are ignored and absent from a fresh clone. Do not assume the external
SO101 checkout or its experiment reports are publicly available.

The upstream checkpoint is already fine-tuned on an SO-100/101 mixture. The
maintainer reports successful zero-shot pick-and-place on the project's SO-101,
meaning no additional training on this project's setup or task was needed for
those trials. These observations are not a quantified benchmark or a general
compatibility guarantee. See
[policy results and adaptation](../../README.md#conversational-robot-tasks).

## Required local layout

| Local path | Required content |
| --- | --- |
| `environments/molmoact2/.venv/bin/python` | Compatible isolated Linux CUDA environment with LeRobot's MolmoAct2 integration |
| `models/molmoact2/runtime/` | Converted SO-101 LeRobot checkpoint and its saved processors |
| `models/molmoact2/source/` | Original checkpoint/config, including official top/side sample images under `assets/` |

The reference installation used links to avoid duplicating about 44 GB of
weights. A link must point to a compatible environment/directory on **your Linux
host**; copying a virtual environment from another machine is not an installation
procedure. A tested standalone dependency lock/installer remains future work.

| Checkpoint | Reference revision |
| --- | --- |
| [lerobot/MolmoAct2-SO100_101-LeRobot](https://huggingface.co/lerobot/MolmoAct2-SO100_101-LeRobot) | `a93b5fcdce4c1e3cc7688c939fc943bf4b092a8a` |
| [allenai/MolmoAct2-SO100_101](https://huggingface.co/allenai/MolmoAct2-SO100_101) | `152569fe57914d97be91055800035f54e250d009` |

Obtain the packages/checkpoints under their upstream terms. Exact prior environment
records lived in `/home/dfin/projects/SO101/experiments/006-molmoact2-zero-shot/`,
which is outside this repository. No complete environment can be reconstructed
from this guide alone.

## Sample-only inference

Once the independent installation is ready, from the repository root:

```bash
printf '%s\n' '{"prompt":"Move the arm towards the lemon and place it in the red bowl."}' \
  | environments/molmoact2/.venv/bin/python scripts/molmoact2_shadow.py
```

This uses the official top/side sample images and sample joint state. It opens
no camera or motor device and discards the predicted commands. The saved processors
apply the converted checkpoint's joint-frame correction; image processing uses a
4:3 crop followed by the checkpoint processor's 378×378 resize. Finite output is
software evidence, not task success or a safe trajectory for the real robot.

The original host check on 2026-09-24 loaded in 52.14 seconds and predicted a
finite 30-by-6 chunk in 1.39 seconds. A negative postprocessed gripper value
illustrated why raw output must not be replayed blindly on hardware.

## Persistent session and live integration

`scripts/molmoact2_session.py` loads once and accepts JSON lines. A task-only
`set_task` uses the official sample observation:

```bash
printf '%s\n' \
  '{"op":"set_task","task":"Move the arm towards the lemon."}' \
  '{"op":"set_task","task":"Place the lemon in the red bowl."}' \
  '{"op":"stop"}' \
  | environments/molmoact2/.venv/bin/python -u scripts/molmoact2_session.py
```

Results are prefixed with `RESULT_JSON:`; invalid requests use `ERROR_JSON:`.
Task changes reset policy and pre/postprocessors before predicting. The worker
itself never opens cameras or motors. The backend's `predict_chunk` operation
can supply fresh camera archives and measured joint state, then hand permitted
postprocessed actions to a separate motor-owning controller. Do not describe
that full UI path as a sample-only or motor-free workflow.

Current UI Molmo input is overhead (`cam0`) and a projected Insta360 X5 view
(`cam1`). Its wrist view is an observer. If one policy camera is unavailable,
the camera worker can duplicate the available view into both inputs; it reports
this fallback, and task quality in that mode is unvalidated. Both missing views
stop capture. X5 projection uses current UI/local settings, not an assumed
training-view match. See [scene setup](../../docs/scene-setup.md) and
[the UI guide](../../ui/README.md).

The live worker prepares 960×720 RGB images; the checkpoint processor performs
its later resize. Original-host frames/traces under `outputs/` and the external
SO101 live runner are historical evidence, not files shipped in this clone.
German prompts pass through unchanged; their quality has not been established
for every task on this installation.

Physical execution and Realtime/Piper task tools require the shared [robot runtime](../robot/README.md)
motor/camera installation, your own calibrated hardware configuration, fresh
scene checks, and supervision. See [known setup gaps](../../docs/configuration.md#known-setup-gaps).
