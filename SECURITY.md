# Security policy

RoboTalk is an experimental personal robotics project. Security fixes are
considered for the current `main` branch; there are no promised maintenance
windows, response deadlines or long-term support releases.

## Report a vulnerability privately

Use [GitHub private vulnerability reporting](https://github.com/BlackChila/SO101-robotalk/security/advisories/new)
when the **Report a vulnerability** button is available under Security → Advisories.
Availability depends on the repository settings; do not assume that private
reporting is enabled.

If private reporting is unavailable, ask
[@BlackChila](https://github.com/BlackChila) for a private reporting channel in a
minimal issue that contains **no vulnerability details, credentials or private
data**. Do not use a public issue or pull request to disclose the finding itself.

Useful information for a private report includes:

- The affected commit, component and relevant configuration.
- What access or information could be obtained, or what unauthorized action
  could occur.
- Minimal reproduction steps using mocks or non-actuating examples where possible.
- Redacted evidence and any mitigation you have identified.

Do not send a real API key, populated `.env`, unreviewed logs or identifying
camera/audio recordings. A software-only report does not require moving a robot.
If a real credential has been exposed, revoke or rotate it through its provider.

## Scope and operating assumptions

The backend is intended to listen on loopback on a prepared Linux host. It is
not configured as a publicly exposed robot-control service. Report origin/access
check bypasses, credential disclosure and unauthorized task or motor-control
paths as security concerns. Ordinary installation problems and documented model
limitations can be reported through the bug template.

Software checks do not certify physical safety. Hardware operations must follow
[scene setup](docs/scene-setup.md) and the [controller rules](AGENTS.md).
See [configuration and privacy](docs/configuration.md) for the local/cloud data paths.
