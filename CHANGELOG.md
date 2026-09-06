# Changelog

## 0.7.0

### Changed

- **The selection screens are checkbox lists, not dropdowns.** Every item is visible at
  once instead of hidden behind a search field, which is the point of a screen whose job
  is "look at what is on offer and tick some of it". Applies to the main menu, the
  datapoint and submenu pickers, and the priority assignment.
- **"Select everything offered above"** on the menu and datapoint screens. Home Assistant
  has no select-all for a checkbox list, so the flow interprets one itself; deselecting
  all is just unticking, which a checkbox list makes easy and a dropdown did not.
- **You can go back.** Home Assistant config flows have no back navigation — no button,
  and no result type for one — so the flow keeps its own history: it snapshots its state
  before each form, and *"◀ Go back to the previous step"* restores the previous one.
  Back works from the priority screen and anywhere in the menu walk, repeatedly, and
  correctly discards what the step being left had collected, so revisiting a screen does
  not add its datapoints twice. At the first step it says so rather than aborting the
  setup.

  Previously the only way to revisit a decision was to abort and start over.

### Fixed

- The submenu form built its schema in four near-identical branches, one of which
  defined `datapoints` twice in the same dict and another of which fell back to
  `vol.Optional(key): ""` — an empty text box where a picker was meant to be. It is one
  schema now, and a field appears only when there is something to put in it.

## 0.6.0

### Added

- **Writeable times of day are entities again.** `TimeOfDay` datapoints — the switching
  times of the controller's programmes — were classified as a `time` entity that no
  platform claimed, so between 0.4.0 and 0.5.0 they were discovered and then silently
  dropped: no entity, no warning. There is a `time` platform now, with its own domain
  toggle in the options.

  The wire format of these datapoints is undocumented and varies by firmware, so both
  `HH:MM` and `HH:MM:SS` are accepted, and a write is rendered in whichever shape the
  device used for its own reading. A reading that cannot be parsed shows as *unknown*
  rather than as a plausible but wrong time, and says so in the log.

  **Breaking for existing entries:** a writeable `TimeOfDay` datapoint that has been
  running as a sensor is migrated to a `time` entity. The old sensor entity is left
  behind in the registry as unavailable and can be deleted; an automation referencing it
  has to be pointed at the new entity. Read-only `TimeOfDay` datapoints stay sensors.

### Documentation

- **The docs now describe this fork.** `manifest.json` pointed Home Assistant's
  "visit documentation" link and every reported issue at the upstream repository, as did
  `ISSUE_URL` in the startup banner and the links throughout the README. All now reach
  this fork, with the original by [@johnaherninfotrack](https://github.com/johnaherninfotrack)
  credited where it belongs.
- **Removed the badge rows** from `README.md` and `info.md`. They advertised release
  0.3.9 long after 0.5.0, claimed pre-commit and Black were in use when neither is
  configured in this repository, and every link pointed upstream.
- Fixed content that was wrong or left over from the project template: a note about
  waking "your vehicle(s)" during installation, the installation steps listed twice,
  `Read/Writ eSwitch`, `teh OZW672`, and a broken link (`https://github.com/:q/...`) in
  `info.md`.
- `CONTRIBUTING.md` described a devcontainer and a pre-commit configuration that do not
  exist in this repository, and told contributors to branch from `master`. It now
  documents how the tests actually run, what CI checks, and the rule for config entry
  schema changes.
- Documented the options dialog, and corrected the claim that HTTPS certificates are
  never verified — that is now an option.

## 0.5.0

### Added

- **Three polling priorities.** The OZW672 reads one datapoint per HTTP request, so
  polling everything at the same rate is what makes a large selection painful on a
  device this small. Every datapoint is now assigned to one of three tiers, each with
  its own coordinator and its own interval:

  | Tier | Default | Option |
  | --- | --- | --- |
  | Priority 1 - fast | 60 s | `scaninterval` |
  | Priority 2 - medium | 300 s | `interval_medium` |
  | Priority 3 - slow | 900 s | `interval_slow` |

  The config flow ends on a new step that sorts the selected datapoints into the fast
  and medium tiers; anything left unpicked stays in the slow tier, so the gentlest
  configuration takes zero clicks. A tier with no datapoints gets no coordinator at all.
- **Priorities can be changed later.** The options dialog now opens on a menu: one
  branch for connection settings and the three intervals, one for re-assigning
  datapoints to tiers without redoing discovery.
- **A configurable pause between requests** (`request_delay`, default 0 s) for a
  controller that struggles under a long poll. All requests already go through a single
  lock, so the three coordinators never talk to the device in parallel.

### Changed

- **Migration is incremental.** Every version bump used to re-read every datapoint
  description from the device - a long, blocking stall at startup for a large
  selection. Each step now runs on its own, and the new 1.5 -> 1.6 step (assigning
  priorities) contacts the device not at all.
- **Existing datapoints migrate to the medium tier (5 minutes).** That is an immediate
  reduction in load compared with the old flat 60-second poll. Raise the few you need
  to be current under the integration's options.
- The config flow reads its schema version from `const.py`. It was hard-coded to 5
  while `const` moved on, so a freshly created entry was immediately considered out of
  date and re-migrated on the next start.

### Infrastructure

- **Continuous integration.** The repository had no CI at all. Every push and pull
  request now runs Home Assistant's `hassfest`, the HACS validation and the full test
  suite, plus a weekly scheduled run so a break in Home Assistant's own checks surfaces
  before a release does.
- **Releases are built and published automatically.** Publishing a GitHub release builds
  `siemens_ozw672.zip` from the integration folder and attaches it; `hacs.json` sets
  `zip_release`, so HACS installs that archive instead of cloning the repository. The
  workflow refuses a tag that disagrees with `manifest.json`.
- `scripts/set_version.py` sets the version in both places that carry it, and a test
  checks that `manifest.json`, `const.VERSION`, the changelog heading and the config
  flow's schema version all agree. It immediately caught `manifest.json` still sitting
  at 0.4.0 while `const.py` had moved to 0.5.0.
- **The release is cut by the workflow, not by hand.** Running the Release workflow with
  `publish` ticked builds the archive, tags the commit and publishes the release, taking
  the release notes from this file's section for the version in `manifest.json` - so the
  release and the changelog cannot drift apart. It refuses to run if that release already
  exists. Publishing from the Releases page by hand still works and takes the same path.
- The release workflow can be dry-run from the Actions tab. It had never executed at
  all, which is a poor thing to discover during an actual release. A manual run does
  everything except the upload and keeps the archive as an artifact, and a new step
  asserts the archive is shaped the way HACS unpacks it - `manifest.json` at the root,
  the platform files present, no `__pycache__`.
- The first CI run failed all three jobs, which is what CI is for. Fixed: `hacs.json`
  still carried `domains` and `iot_class`, which HACS now rejects outright; the setup
  step's description contained a URL, which hassfest forbids in translation strings;
  the integration implements `async_setup` without declaring a `CONFIG_SCHEMA`; and
  `actions/setup-python`'s pip cache only looks for `requirements.txt` or
  `pyproject.toml` and hard-fails when it finds neither. All four are now covered by
  local tests, so the next one costs two seconds instead of a round trip through
  GitHub Actions.
- `requirements_test.txt` pins the Home Assistant version the suite is verified against -
  **2026.8.3 on Python 3.14** - and documents that the pin and CI's `python-version` move
  together.
- The entity tests no longer hard-code entity ids. Home Assistant decides that naming
  itself and changed it in 2026.8: an entity attached to a device is now prefixed with
  the device name (`sensor.rvs43_outside_temp`, not `sensor.outside_temp`). The tests key
  on our own unique ids instead, and pass unchanged on both 2025.12 and 2026.8.

## 0.4.0

### Fixed

- **`number.py` crashed on writeable energy datapoints.** `SiemensOzw672EnergyControl`
  referenced `ICON_POWER` without importing it, so every state read of a writeable
  kWh/Wh/kW/W datapoint raised `NameError`.
- **Missing readings were recorded as zero.** The device's no-data sentinel (`----`)
  was rewritten to `"0"` in the API client before it ever reached an entity, so a
  datapoint with no reading was recorded as a real zero in long-term statistics. It is
  now passed through and the entity becomes unknown.
- **Options never took effect.** The update listener rewrote the registry by hand but
  never reloaded the config entry, so a changed scan interval, HTTP timeout or retry
  count did nothing until Home Assistant was restarted.
- **The five domain toggles did nothing.** `switch`/`select`/`number`/`binary_sensor`/
  `sensor` were shown in the options dialog, stored, and never read anywhere.
- **`UnboundLocalError` during migration.** `_get_sysinfo()` and `_get_devices()` caught
  every exception with `pass` and then returned a variable that was never assigned.
- **One unreadable datapoint took the whole integration down.** A datapoint the OZW672
  could not return was dropped from the poll result, and every entity then raised
  `KeyError`. Failing datapoints are now skipped and reported as unavailable
  individually; only a poll that reads nothing at all fails.
- **`KeyError` on descriptions without `DecimalDigits`, `Min`, `Max` or `Resolution`.**
  The number platform subscripted all four directly. A resolution of `0` no longer
  produces a zero step.
- **Retry logic never gave up cleanly.** `api_wrapper()` swallowed every exception, fell
  out of its loop and returned `None`, so callers failed on `None["Result"]` far from the
  cause. `httpretries: 0` meant no request was issued at all. Failures now raise
  `SiemensOzw672ApiError`, and options are clamped to a usable range.
- **Duplicate entities when reconfiguring.** Selecting an already-configured device set
  the same unique id and then created a second config entry beside the first. The
  existing entry is now updated instead.
- **Wrong device names in the selection list.** The name loop had no `break`, so the last
  device in the list decided the name shown for every entry.
- **Config flow could return `None`.** Submitting the main menu with nothing selected
  produced a flow step with no result. It now aborts with a message.
- **Writeable `TimeOfDay` datapoints vanished.** They were classified as a `time` entity,
  but there is no time platform, so no platform claimed them. They are read-only sensors
  for now.
- Failed writes are reported. `async_write_data()` results were assigned and dropped, so a
  rejected write looked identical to a successful one.
- `device_state_attributes` (unused since Home Assistant 0.109) is now
  `extra_state_attributes`, and reports the datapoint id and operating line.
- `_LOGGER.warn` → `_LOGGER.warning`; the poll timer uses a monotonic clock.

### Changed

- **HTTPS certificate verification is now an option** (`verify_ssl`, default off) instead
  of being hard-coded off. The deprecated aiohttp `verify_ssl=` argument was replaced
  with `ssl=`.
- The username is URL-encoded like the password already was, so special characters no
  longer break the login. Passwords are redacted from logged URLs.
- All requests to the device go through a single lock, so the OZW672 never sees parallel
  requests however many entities call in.
- The five platforms share one setup path (`helpers.py`) instead of five copies of it, and
  no longer write runtime keys back into the stored config entry.
- Generic numeric sensors report the unit the device sends (bar, h, min, …) instead of
  dropping it. **Existing entities of this kind will report a unit change to the
  statistics engine once.**
- `device_info` reports Siemens as the manufacturer and the controller type as the model,
  instead of the integration name and the integration version.
- `manifest.json` declares `iot_class` and `integration_type`; `hacs.json` now requires
  Home Assistant 2024.11, the first release where `OptionsFlow.config_entry` is populated
  by Home Assistant itself.

### Tests

- Test suite grows from 38 to 82 tests; coverage from 25% to 63%. New: end-to-end config
  entry setup across all five platforms, API client transport behaviour, and the shared
  helpers.
