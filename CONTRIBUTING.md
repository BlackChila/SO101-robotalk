# Contributing to RoboTalk

This is an experimental SO-101 project developed on Linux ARM64 / NVIDIA GB10.
The current setup is specific to the reference robot. Read the
[README](README.md), [installation guide](docs/getting-started.md), and
[known setup gaps](docs/configuration.md#known-setup-gaps) first.

## Report a problem

Use a GitHub issue when issues are available. Include:

- What you expected, what happened, and the smallest reproduction steps.
- Commit, Linux distribution/architecture, GPU/driver, and Python environment.
- Conversation mode and optional MolmoAct2 model and checkpoint revision.
- Whether the check used mocks, synthetic inputs, live cameras, or physical motion.
- Relevant redacted errors and controller status, including whether a hold was verified.

Do not attach credentials, `.env` contents, private conversations, identifiable
camera images without permission, or full unreviewed logs. Report suspected
credential exposure privately through an available maintainer contact or GitHub
private vulnerability reporting if enabled; do not put the secret in an issue.

## Propose a change

Discuss dependency changes, new hardware support, model-frame conversions, and
motor-control behavior before changing them. Keep each model environment isolated;
do not regenerate Linux locks on another platform to resolve a local install error.
Do not commit downloaded weights, third-party checkouts, calibration files,
virtual environments, caches, or trial output.

For a documentation change, check links, paths, command options, and whether a
statement describes current behavior or a dated trial. Do not promote a software
test into a claim of hardware validation.

For software changes on a prepared Linux test host, run the relevant existing
checks. The frontend uses Node's built-in test runner:

```bash
node --test ui/src/*.test.js
npm --prefix ui run build
```

Python tests use `unittest`; some import the API and need packages beyond the
standalone ASR project's lock. There is currently no complete, independently
locked development/test environment. Use a prepared compatible test environment
and run the relevant files, for example:

```bash
python -m unittest discover -s tests -p 'test_camera_profiles.py'
```

Physical tests require scene checks, calibration, operator supervision, and a
physical cutoff. Follow the controller exit rules in [AGENTS.md](AGENTS.md).
A change must preserve a verified measured-position torque-on hold on stop and
disconnect unless the operator explicitly requests torque off. Report any
unverified hold immediately. Record physical results separately from software checks.

## Licensing

Original project code and documentation use
[Apache-2.0](https://www.apache.org/licenses/LICENSE-2.0); see
[LICENSE](LICENSE), [NOTICE](NOTICE), and the
[README's scope notice](README.md#contributing-and-licensing).
Please offer original contributions under the same terms and confirm that you
have permission to do so, including any employer or university obligations.
Third-party code, model weights, voices, and media retain their own terms;
identify their origin, include required notices, and review permission and license
compatibility before adding them. The bundled demo assets remain
excluded from the project license pending that review.
Preserve applicable attribution notices and identify changes to redistributed
files as required by Apache-2.0. The license for original contributions does not
remove the GPL obligations of a distributed combined Piper program or the terms
of other upstream materials.
