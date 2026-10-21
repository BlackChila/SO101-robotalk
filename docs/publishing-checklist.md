# Publication and release checklist

SO101-robotalk continues the conversation functionality of
[2026-PG-robotalk](https://github.com/BlackChila/2026-PG-robotalk). This checklist
distinguishes source migration from a validated release. See the
[historical review](publication-review.md) for the source's earlier review scope.

## Source and documentation

- [x] Retain the original [Apache-2.0 license](../LICENSE) and [attribution](../NOTICE).
- [x] Document the conversation homepage, three speech modes and optional MolmoAct2 tasks.
- [x] Omit the control workspace, FLUX/Galaxea integrations and experimental guides.
- [x] Identify robot-specific configuration, external MolmoAct2 setup and Linux limitations.
- [x] Keep populated `.env`, model weights, calibration, caches and generated outputs ignored.
- [ ] Recheck the cleaned snapshot for credentials and identifying details before wider redistribution.
- [ ] Review any demonstration media for privacy and redistribution permission.

## Licensing and packaging

- [ ] Confirm rights to the bundled intro audio and gesture data; code licensing alone does not settle them.
- [ ] Check the actual model and voice licenses for downloaded revisions before redistributing them.
- [ ] Retain all required upstream notices in any packaged environment.
- [ ] Meet applicable GPL notices/source requirements for a distributed combined Piper program.
- [ ] Review the new shared robot runtime and external MolmoAct2 environment; inherited metadata is not a complete current audit.

## Installation and behavior

- [ ] Reproduce the documented installation in a clean Linux ARM64/GB10 checkout.
- [ ] Validate the shared robot runtime dependencies and optional speech/model installations on that host.
- [ ] Supply or validate an independent reproducible MolmoAct2 installer/lock.
- [ ] Verify ASR and all advertised speech modes; separately accept live Qwen voice/tool behavior.
- [ ] Verify inference first with hardware-free inputs, then commission physical behavior under supervision.
- [ ] Check fresh camera exposure/framing, own calibration, torque-on hold, explicit torque-off, task stop, reset, return/recovery and tracking.
- [ ] Record real outcomes without treating a stopped run, a model output or a mocked test as manipulation success.

## Repository presentation

- [ ] Enable private vulnerability reporting if desired; the [security policy](../SECURITY.md) provides a fallback.
- [ ] Add an intentional screenshot/demo with captions explaining the behavior demonstrated.
- [ ] Choose a tag/release only with exact revisions and known limitations.

The project can publish useful experimental source while release acceptance is
incomplete. No promised support schedule or general hardware compatibility is implied.
