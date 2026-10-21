## Change and reason

Describe the problem and the resulting behavior. Link the related issue if any.

## Validation

List the checks you actually ran and their results. Distinguish documentation,
software/mocked checks, model inference and supervised physical tests. If a
relevant check could not be run, state that limitation.

## Scope

- [ ] I read the [contribution guide](https://github.com/BlackChila/SO101-robotalk/blob/main/CONTRIBUTING.md) and [code of conduct](https://github.com/BlackChila/SO101-robotalk/blob/main/CODE_OF_CONDUCT.md).
- [ ] I did not commit credentials, model weights, local calibration, environments or trial output.
- [ ] I identified any third-party material and its applicable license/notices.
- [ ] I discussed changes to dependencies, hardware support or motor behavior when applicable.

For a physical-controller change, describe how stop, fault and disconnect
preserve the verified measured-position torque-on hold. Explicit operator torque
off remains an exception. Do not claim hardware validation from software tests.
