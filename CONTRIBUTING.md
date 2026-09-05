# Contribution guidelines

This is a fork of
[johnaherninfotrack/homeassistant_custom_siemensozw672](https://github.com/johnaherninfotrack/homeassistant_custom_siemensozw672).
Issues and pull requests for **this fork** belong
[here](https://github.com/michaelf988/homeassistant_custom_siemensozw672/issues); if your
problem also exists in the original integration, upstream is the better place for it.

Contributing should be as easy and transparent as possible, whether it is reporting a bug,
discussing the current state of the code, submitting a fix, or proposing a feature.

## Reporting bugs

Report bugs by [opening an issue](../../issues/new/choose). **Please enable debug logging
and attach the logs** — without them most OZW672 problems cannot be diagnosed, because the
device's behaviour varies by firmware and plant:

```yaml
logger:
  default: info
  logs:
    custom_components.siemens_ozw672: debug
```

Credentials and session IDs are redacted from the logs, but skim them before posting.

A good report has a quick summary, the steps to reproduce, what you expected, what actually
happened, and your Home Assistant and OZW672 firmware versions.

## Pull requests

1. Fork the repo and branch from `main`.
2. Make the change, and add or update tests for it.
3. Update the documentation if behaviour changed.
4. Add a `CHANGELOG.md` entry under the unreleased version.
5. Make sure the test suite passes.
6. Open the pull request.

## Running the tests

```console
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
python -m pytest
```

`requirements_test.txt` pins the Home Assistant version the suite runs against — currently
**2026.8.3, which requires Python 3.14**. The pin and the `python-version` in
`.github/workflows/validate.yml` move together: each release of
`pytest-homeassistant-custom-component` vendors one Home Assistant version and requires a
specific minimum Python.

The suite needs no OZW672. `const.py` carries a `TESTDATA` fixture, and an API client
constructed with the host `test` serves from it instead of the network, so config flow and
entity tests run end to end offline.

## What CI checks

Every push and pull request runs:

- **hassfest** — Home Assistant's own manifest and translation validation.
- **HACS validation** — repository and `hacs.json` checks.
- **The test suite**.

`tests/test_manifests.py` reproduces the hassfest and HACS rules locally, so the common
failures (a URL in a translation string, an unknown `hacs.json` key, an untranslated config
flow step) surface in a two-second test run rather than a round trip through GitHub Actions.

`tests/test_version_consistency.py` checks that `manifest.json`, `const.VERSION`, the
changelog heading and the config flow's schema version all agree.

## Code style

Match the surrounding code. `setup.cfg` carries the flake8 and isort configuration; there is
no enforced formatter, and no pre-commit configuration in this repository.

## Config entry schema changes

If a change alters the shape of stored config entry data, bump `CONF_MINOR_VERSION` in
`const.py` and add a migration step to `async_migrate_entry`. Keep each step separate and
guarded by the version it applies to — the migration used to re-read every datapoint
description from the device on any version bump, which is a long, blocking stall at startup
for a large selection. A purely local schema change should not contact the device at all.

## License

By contributing, you agree that your contributions will be licensed under the project's
[MIT License](LICENSE).
