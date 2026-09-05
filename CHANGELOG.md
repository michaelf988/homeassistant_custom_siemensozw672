# Changelog

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
