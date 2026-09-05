"""Tests for the config entry migration steps.

The migration used to re-read every datapoint description from the device on any
version bump, whatever the change was. That is a lot of traffic for a controller
this small, so each step now runs on its own and the 1.5 -> 1.6 step (assigning a
polling priority) touches nothing but the stored data.
"""
from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.siemens_ozw672 import async_migrate_entry
from custom_components.siemens_ozw672.const import (
    CONF_DATAPOINTS,
    CONF_DEVICE,
    CONF_DEVICE_LONGNAME,
    CONF_HOST,
    CONF_MINOR_VERSION,
    CONF_PASSWORD,
    CONF_PRIORITY,
    CONF_PROTOCOL,
    CONF_USERNAME,
    CONF_VERSION,
    DEFAULT_PRIORITY,
    DOMAIN,
    PRIORITY_FAST,
)

LEGACY_DATAPOINTS = [
    {"Id": "1960", "OpLine": "39", "Name": "Outside temp", "MenuItem": "Diagnostics",
     "WriteAccess": "false", "DPDescr": {"Type": "Numeric", "HAType": "sensor"}},
    {"Id": "1439", "OpLine": "3516", "Name": "DHW setpoint", "MenuItem": "DHW",
     "WriteAccess": "true", "DPDescr": {"Type": "Numeric", "HAType": "number"}},
]


def _entry(hass, minor_version, datapoints=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=minor_version,
        entry_id="migration_entry",
        data={
            CONF_HOST: "test",
            CONF_PROTOCOL: "http",
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_DEVICE: "RVS43",
            CONF_DEVICE_LONGNAME: "0.1 RVS43.345/109",
            CONF_DATAPOINTS: datapoints if datapoints is not None else LEGACY_DATAPOINTS,
        },
        options={},
    )
    entry.add_to_hass(hass)
    return entry


async def test_existing_datapoints_get_the_default_priority(hass):
    """Everything configured before priorities existed lands in the middle tier."""
    entry = _entry(hass, minor_version=5)

    assert await async_migrate_entry(hass, entry) is True

    assert entry.minor_version == CONF_MINOR_VERSION
    assert entry.version == CONF_VERSION
    assert all(dp[CONF_PRIORITY] == DEFAULT_PRIORITY for dp in entry.data[CONF_DATAPOINTS])


async def test_the_priority_step_does_not_touch_the_device(hass):
    """A purely local schema change must not re-read every description.

    On a controller with a large selection that re-read is a long, blocking stall
    at startup, so it has to stay behind the version that actually needs it.
    """
    entry = _entry(hass, minor_version=5)

    with patch(
        "custom_components.siemens_ozw672.api.SiemensOzw672ApiClient.async_get_data_descr"
    ) as descr, patch(
        "custom_components.siemens_ozw672.api.SiemensOzw672ApiClient.async_get_data"
    ) as data:
        assert await async_migrate_entry(hass, entry) is True

    descr.assert_not_called()
    data.assert_not_called()


async def test_an_explicit_priority_survives_migration(hass):
    """A datapoint that already carries a tier keeps it."""
    datapoints = [{**LEGACY_DATAPOINTS[0], CONF_PRIORITY: PRIORITY_FAST},
                  LEGACY_DATAPOINTS[1]]
    entry = _entry(hass, minor_version=5, datapoints=datapoints)

    assert await async_migrate_entry(hass, entry) is True

    stored = {dp["Id"]: dp[CONF_PRIORITY] for dp in entry.data[CONF_DATAPOINTS]}
    assert stored == {"1960": PRIORITY_FAST, "1439": DEFAULT_PRIORITY}


async def test_an_up_to_date_entry_is_left_alone(hass):
    """No work, and no device traffic, when there is nothing to migrate."""
    entry = _entry(hass, minor_version=CONF_MINOR_VERSION)

    with patch(
        "custom_components.siemens_ozw672.api.SiemensOzw672ApiClient.async_get_data"
    ) as data:
        assert await async_migrate_entry(hass, entry) is True

    data.assert_not_called()


async def test_older_entries_still_run_the_description_refresh(hass):
    """The 1.4 -> 1.5 step is still applied for entries that never had it."""
    entry = _entry(hass, minor_version=4)

    assert await async_migrate_entry(hass, entry) is True

    assert entry.minor_version == CONF_MINOR_VERSION
    # The descriptions came back from the TESTDATA device, and the new step ran
    # on top of them.
    stored = {dp["Id"]: dp for dp in entry.data[CONF_DATAPOINTS]}
    assert stored["1439"]["DPDescr"]["Unit"] == "°C"
    assert stored["1439"][CONF_PRIORITY] == DEFAULT_PRIORITY
