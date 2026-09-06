"""Tests for the shared helpers.

These cover the behaviour the five platforms used to reimplement (badly) in a
copy-pasted setup loop, plus the option clamping that keeps an out-of-range
stored option from breaking the poller.
"""
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.siemens_ozw672.const import (
    CONF_DATAPOINTS,
    CONF_DEVICE,
    CONF_DEVICE_LONGNAME,
    CONF_PREFIX_FUNCTION,
    CONF_PREFIX_OPLINE,
    CONF_SCANINTERVAL,
    CONF_USE_DEVICE_LONGNAME,
    DEFAULT_SCANINTERVAL,
    DOMAIN,
    MAX_SCANINTERVAL,
    MIN_SCANINTERVAL,
)
from datetime import time

from custom_components.siemens_ozw672.helpers import (
    build_dp_configs,
    format_time,
    parse_time,
    clean_value,
    datapoint_identifier,
    decimal_digits,
    descr_float,
    device_model,
    device_name,
    dp_configs_for_hatype,
    option_int,
    platform_enabled,
)

DATAPOINTS = [
    {
        "Id": "1960",
        "WriteAccess": "false",
        "OpLine": "39",
        "Name": "Outside temp",
        "MenuItem": "Diagnostics",
        "DPDescr": {"Type": "Numeric", "HAType": "sensor", "DecimalDigits": "1"},
    },
    {
        "Id": "1438",
        "WriteAccess": "true",
        "OpLine": "0",
        "Name": "DHW operating mode",
        "MenuItem": "DHW",
        "DPDescr": {"Type": "Enumeration", "HAType": "switch"},
    },
]


def _entry(hass, data=None, options=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_DEVICE: "RVS43",
            CONF_DEVICE_LONGNAME: "0.1 RVS43.345/109",
            CONF_DATAPOINTS: DATAPOINTS,
            CONF_PREFIX_FUNCTION: True,
            CONF_PREFIX_OPLINE: True,
            **(data or {}),
        },
        options=options or {},
        entry_id="helper_entry",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("   19.8", "19.8"), ("On", "On"), ("----", None), ("--", None), ("", None), (None, None)],
)
def test_clean_value(raw, expected):
    """Padding is stripped and the device's no-data sentinel becomes None."""
    assert clean_value(raw) == expected


def test_decimal_digits_missing_key_does_not_raise():
    """A description without DecimalDigits yields None instead of KeyError."""
    assert decimal_digits({"DPDescr": {"Type": "Numeric"}}) is None
    assert decimal_digits({}) is None
    assert decimal_digits({"DPDescr": {"DecimalDigits": "2"}}) == 2


def test_descr_float_falls_back():
    """Min/Max/Resolution are optional; a missing one uses the fallback."""
    assert descr_float({"DPDescr": {"Min": "-50.0"}}, "Min", 0.0) == -50.0
    assert descr_float({"DPDescr": {}}, "Max", 100.0) == 100.0
    assert descr_float({"DPDescr": {"Resolution": "not a number"}}, "Resolution", 1.0) == 1.0


def test_datapoint_identifier_prefers_opline():
    """The operating line is stable across menu tree regenerations; the API Id is not."""
    assert datapoint_identifier({"Id": "1960", "OpLine": "39"}) == "39"
    # OpLine 0 or 1 carries no information, so fall back to the API Id.
    assert datapoint_identifier({"Id": "1438", "OpLine": "0"}) == "001438"
    assert datapoint_identifier({"Id": "1438", "OpLine": "nonsense"}) == "001438"


async def test_build_dp_configs_does_not_mutate_the_config_entry(hass):
    """Runtime keys stay out of the stored config entry.

    The platforms used to write entry_id/device_id/device_name/entity_prefix into
    the dicts inside entry.data["datapoints"], so setting up entities mutated -
    and eventually persisted - the config entry as a side effect.
    """
    entry = _entry(hass)

    configs = build_dp_configs(entry)

    assert configs[0]["entry_id"] == "helper_entry_39"
    assert configs[0]["device_id"] == "helper_entry"
    assert configs[0]["entity_prefix"] == "Diagnostics - 39 "
    for stored in entry.data[CONF_DATAPOINTS]:
        assert "entry_id" not in stored
        assert "entity_prefix" not in stored


async def test_prefix_flags_switch_the_entity_prefix_off(hass):
    """Both naming prefixes are honoured independently."""
    entry = _entry(hass, data={CONF_PREFIX_FUNCTION: False, CONF_PREFIX_OPLINE: False})

    assert build_dp_configs(entry)[0]["entity_prefix"] == ""


async def test_device_name_follows_the_longname_option(hass):
    """The option, not the stale copy in data, decides the device name."""
    entry = _entry(hass, options={CONF_USE_DEVICE_LONGNAME: True})
    assert device_name(entry) == "0.1 RVS43.345/109"

    entry = _entry(hass, options={CONF_USE_DEVICE_LONGNAME: False})
    assert device_name(entry) == "RVS43"


async def test_device_model_strips_the_bus_address(hass):
    """The model is the type, without the LPB/BSB address in front of it."""
    assert device_model(_entry(hass)) == "RVS43.345/109"


async def test_dp_configs_for_hatype_filters(hass):
    """Each platform only sees the datapoints it is responsible for."""
    entry = _entry(hass)

    assert [c["Id"] for c in dp_configs_for_hatype(entry, "sensor")] == ["1960"]
    assert [c["Id"] for c in dp_configs_for_hatype(entry, "switch")] == ["1438"]
    assert dp_configs_for_hatype(entry, "select") == []


async def test_platform_enabled_reads_the_domain_toggles(hass):
    """The five domain toggles in the options dialog are actually honoured.

    They were shown, stored, and then never read anywhere.
    """
    entry = _entry(hass, options={"switch": False})

    assert platform_enabled(entry, "switch") is False
    assert platform_enabled(entry, "sensor") is True


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (None, DEFAULT_SCANINTERVAL),
        (300, 300),
        # A scan interval of 0 turned the coordinator into a tight polling loop.
        (0, MIN_SCANINTERVAL),
        (-5, MIN_SCANINTERVAL),
        (10**9, MAX_SCANINTERVAL),
        ("not a number", DEFAULT_SCANINTERVAL),
    ],
)
async def test_option_int_clamps_unusable_values(hass, stored, expected):
    """Stored options are re-validated on read, not trusted."""
    options = {} if stored is None else {CONF_SCANINTERVAL: stored}
    entry = _entry(hass, options=options)

    assert option_int(
        entry, CONF_SCANINTERVAL, DEFAULT_SCANINTERVAL, MIN_SCANINTERVAL, MAX_SCANINTERVAL
    ) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("06:30", time(6, 30)),
        ("  06:30 ", time(6, 30)),
        ("6:30", time(6, 30)),
        ("06:30:00", time(6, 30)),
        ("23:59:59", time(23, 59, 59)),
        ("00:00", time(0, 0)),
        # The device's no-data sentinel and anything unreadable.
        ("----", None),
        ("", None),
        (None, None),
        ("not a time", None),
        ("25:00", None),
    ],
)
def test_parse_time(raw, expected):
    """The TimeOfDay wire format is undocumented, so both shapes are accepted."""
    assert parse_time(raw) == expected


@pytest.mark.parametrize(
    ("value", "like", "expected"),
    [
        # Writing seconds to a datapoint that reports none is what this hardware
        # rejects silently, so the reading is the template.
        (time(6, 30), "07:00", "06:30"),
        (time(6, 30), "07:00:00", "06:30:00"),
        (time(6, 30, 15), "07:00", "06:30"),
        (time(6, 30), None, "06:30"),
        (time(6, 30), "----", "06:30"),
    ],
)
def test_format_time_matches_the_reported_shape(value, like, expected):
    """A write is rendered the way the device renders its own reading."""
    assert format_time(value, like) == expected
