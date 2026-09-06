"""End-to-end setup of a config entry against the built-in TESTDATA device.

Nothing exercised the entity platforms before, which is why a NameError in
number.py (ICON_POWER was used but never imported) shipped in a release: the
class it sits on is only reached by a *writeable* energy datapoint.
"""
import copy

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.siemens_ozw672.const import (
    CONF_DATAPOINTS,
    CONF_INTERVAL_MEDIUM,
    CONF_INTERVAL_SLOW,
    CONF_PRIORITY,
    CONF_SCANINTERVAL,
    PRIORITY_FAST,
    PRIORITY_MEDIUM,
    PRIORITY_SLOW,
    CONF_DEVICE,
    CONF_DEVICE_ID,
    CONF_DEVICE_LONGNAME,
    CONF_HOST,
    CONF_MINOR_VERSION,
    CONF_PASSWORD,
    CONF_PREFIX_FUNCTION,
    CONF_PREFIX_OPLINE,
    CONF_PROTOCOL,
    CONF_USERNAME,
    CONF_VERSION,
    DEFAULT_OPTIONS,
    DOMAIN,
)


def _dp(id, opline, name, dptype, hatype, priority=PRIORITY_MEDIUM, **descr):
    return {
        "Id": id,
        "WriteAccess": "true" if hatype in ("switch", "select", "number") else "false",
        "OpLine": opline,
        "Name": name,
        "MenuItem": "Diagnostics",
        CONF_PRIORITY: priority,
        "DPDescr": {"Type": dptype, "HAType": hatype, **descr},
    }


ENTRY_ID = "entity_entry"

DATAPOINTS = [
    _dp("1960", "39", "Outside temp", "Numeric", "sensor", priority=PRIORITY_FAST, DecimalDigits="1"),
    # The device reports "----" for this one: no reading at all.
    _dp("1963", "44", "Flow temp", "Numeric", "sensor", DecimalDigits="1"),
    _dp("1961", "40", "Energy total", "Numeric", "sensor", priority=PRIORITY_SLOW, DecimalDigits="0"),
    # Writeable energy - the only shape that reaches SiemensOzw672EnergyControl.
    _dp("1962", "41", "Energy setpoint", "Numeric", "number",
        Min="0.000000", Max="100000.000000", Resolution="1.000000", DecimalDigits="1"),
    _dp("1439", "3516", "DHW setpoint", "Numeric", "number",
        Min="45.000000", Max="60.000000", Resolution="1.000000", DecimalDigits="0"),
    _dp("1438", "3514", "DHW operating mode", "Enumeration", "switch"),
    _dp("1441", "3522", "DHW release", "Enumeration", "select",
        Enums=[{"Text": "24h/day", "Value": "0"},
               {"Text": "Heating programs with forward shift", "Value": "1"},
               {"Text": "Time switch program 4", "Value": "2"}]),
    _dp("1966", "5328", "Heat circuit pump 1", "RadioButton", "binarysensor"),
    # A writeable switching time - the shape the time platform exists for.
    _dp("1970", "3560", "Standby start", "TimeOfDay", "time"),
]


def _entry(hass, datapoints=None, options=None):
    """A config entry pointed at the built-in "test" host, so no network is used."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONF_VERSION,
        minor_version=CONF_MINOR_VERSION,
        entry_id=ENTRY_ID,
        title="RVS43",
        data={
            CONF_HOST: "test",
            CONF_PROTOCOL: "http",
            CONF_USERNAME: "user",
            CONF_PASSWORD: "pass",
            CONF_DEVICE: "RVS43",
            CONF_DEVICE_LONGNAME: "0.1 RVS43.345/109",
            CONF_DEVICE_ID: "00FD3100033C:008600004EBF",
            CONF_DATAPOINTS: copy.deepcopy(datapoints if datapoints is not None else DATAPOINTS),
            # Prefixes off so entity ids stay predictable in the assertions.
            CONF_PREFIX_FUNCTION: False,
            CONF_PREFIX_OPLINE: False,
        },
        options={**DEFAULT_OPTIONS, CONF_PREFIX_FUNCTION: False, CONF_PREFIX_OPLINE: False,
                 **(options or {})},
    )
    entry.add_to_hass(hass)
    return entry


async def _setup(hass, **kwargs):
    entry = _entry(hass, **kwargs)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entity_id(hass, domain, opline):
    """Look an entity up by its unique id rather than guessing its entity_id.

    Home Assistant decides entity_id naming itself and has changed it: from
    2026.8 an entity attached to a device is prefixed with the device name
    ("sensor.rvs43_outside_temp", not "sensor.outside_temp"). The unique id is
    ours, so that is what the tests key on.
    """
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"{ENTRY_ID}_{opline}"
    )


def _state(hass, domain, opline):
    """The state object of the entity for one datapoint, or None if it has none."""
    entity_id = _entity_id(hass, domain, opline)
    return hass.states.get(entity_id) if entity_id else None


# Operating line numbers of the fixture datapoints, which are also their unique
# id suffixes.
OUTSIDE_TEMP = "39"
FLOW_TEMP = "44"
ENERGY_TOTAL = "40"
ENERGY_SETPOINT = "41"
DHW_SETPOINT = "3516"
DHW_MODE = "3514"
DHW_RELEASE = "3522"
PUMP = "5328"
STANDBY_START = "3560"


async def test_every_platform_produces_its_entities(hass):
    """One datapoint of each shape ends up in the right domain."""
    await _setup(hass)

    assert _state(hass, "sensor", OUTSIDE_TEMP) is not None
    assert _state(hass, "sensor", ENERGY_TOTAL) is not None
    assert _state(hass, "number", ENERGY_SETPOINT) is not None
    assert _state(hass, "number", DHW_SETPOINT) is not None
    assert _state(hass, "switch", DHW_MODE) is not None
    assert _state(hass, "select", DHW_RELEASE) is not None
    assert _state(hass, "binary_sensor", PUMP) is not None
    assert _state(hass, "time", STANDBY_START) is not None


async def test_writeable_energy_entity_renders(hass):
    """SiemensOzw672EnergyControl used to raise NameError: ICON_POWER.

    The class referenced ICON_POWER without importing it, so reading the state of
    a writeable kWh datapoint blew up.
    """
    await _setup(hass)

    state = _state(hass, "number", ENERGY_SETPOINT)
    assert state.state == "120.0"
    assert state.attributes["icon"] == "mdi:lightning-bolt"
    assert state.attributes["unit_of_measurement"] == "kWh"
    assert state.attributes["device_class"] == "energy"


async def test_decimals_are_not_truncated(hass):
    """A reading of " 15.8" stays 15.8 rather than being truncated to 15."""
    assert (await _setup(hass)) is not None

    assert _state(hass, "sensor", OUTSIDE_TEMP).state == "15.8"


async def test_missing_reading_is_unknown_not_zero(hass):
    """The device's "----" sentinel must not be recorded as a real zero."""
    await _setup(hass)

    assert _state(hass, "sensor", FLOW_TEMP).state == "unknown"


async def test_descriptions_without_min_max_do_not_break_number_entities(hass):
    """A description missing Min/Max/Resolution/DecimalDigits used to raise KeyError."""
    datapoints = copy.deepcopy(DATAPOINTS)
    for datapoint in datapoints:
        if datapoint["Id"] == "1439":
            datapoint["DPDescr"] = {"Type": "Numeric", "HAType": "number"}

    await _setup(hass, datapoints=datapoints)

    state = _state(hass, "number", DHW_SETPOINT)
    assert state.state == "52.0"
    assert state.attributes["min"] == 0.0
    assert state.attributes["max"] == 100.0
    assert state.attributes["step"] == 1.0


async def test_select_options_come_from_the_description(hass):
    """The enum list drives the options and the current value is one of them."""
    await _setup(hass)

    state = _state(hass, "select", DHW_RELEASE)
    assert state.state == "24h/day"
    assert state.attributes["options"] == [
        "24h/day", "Heating programs with forward shift", "Time switch program 4",
    ]


async def test_select_without_enums_does_not_raise(hass):
    """A select whose description carries no Enums reports no options, not KeyError."""
    datapoints = copy.deepcopy(DATAPOINTS)
    for datapoint in datapoints:
        if datapoint["Id"] == "1441":
            datapoint["DPDescr"] = {"Type": "Enumeration", "HAType": "select"}

    await _setup(hass, datapoints=datapoints)

    state = _state(hass, "select", DHW_RELEASE)
    assert state.attributes["options"] == []
    # The reported value is not a known option, so it is not claimed as the state.
    assert state.state == "unknown"


async def test_disabled_domain_creates_no_entities(hass):
    """The five domain toggles were stored in the options and never read."""
    await _setup(hass, options={"switch": False})

    assert _entity_id(hass, "switch", DHW_MODE) is None
    assert _state(hass, "sensor", OUTSIDE_TEMP) is not None


async def test_entities_do_not_write_back_into_the_config_entry(hass):
    """Setting up entities must not mutate the stored datapoint dicts."""
    entry = await _setup(hass)

    for stored in entry.data[CONF_DATAPOINTS]:
        assert "entry_id" not in stored
        assert "device_name" not in stored


async def test_unique_ids_use_the_operating_line(hass):
    """Entity ids survive the OZW672 regenerating its menu tree."""
    await _setup(hass)

    registry = er.async_get(hass)
    entity_id = _entity_id(hass, "sensor", OUTSIDE_TEMP)
    assert entity_id is not None
    assert registry.async_get(entity_id).unique_id == f"{ENTRY_ID}_{OUTSIDE_TEMP}"


async def test_one_coordinator_per_populated_tier(hass):
    """Each polling tier that has datapoints gets its own coordinator and interval."""
    entry = await _setup(hass)
    runtime = hass.data[DOMAIN][entry.entry_id]

    intervals = {
        priority: coordinator.update_interval.total_seconds()
        for priority, coordinator in runtime.coordinators.items()
    }
    assert intervals == {PRIORITY_FAST: 60, PRIORITY_MEDIUM: 300, PRIORITY_SLOW: 900}
    # One client shared by all three, so the request lock still serialises everything.
    assert {id(c.api) for c in runtime.coordinators.values()} == {id(runtime.client)}


async def test_empty_tiers_get_no_coordinator(hass):
    """A tier with no datapoints must not poll the device for an empty list."""
    datapoints = [dp for dp in copy.deepcopy(DATAPOINTS) if dp["Id"] in ("1960", "1963")]
    for datapoint in datapoints:
        datapoint[CONF_PRIORITY] = PRIORITY_FAST

    entry = await _setup(hass, datapoints=datapoints)

    assert set(hass.data[DOMAIN][entry.entry_id].coordinators) == {PRIORITY_FAST}


async def test_each_entity_binds_to_its_own_tier(hass):
    """An entity reads from the coordinator that actually polls its datapoint."""
    entry = await _setup(hass)
    runtime = hass.data[DOMAIN][entry.entry_id]

    # The fast tier only ever polls its own datapoints.
    assert set(runtime.coordinators[PRIORITY_FAST].data) == {"1960"}
    assert "1961" in runtime.coordinators[PRIORITY_SLOW].data
    # ... and both entities still resolve their value.
    assert _state(hass, "sensor", OUTSIDE_TEMP).state == "15.8"
    assert _state(hass, "sensor", ENERGY_TOTAL).state == "15.0"


async def test_changing_intervals_reloads_the_entry(hass):
    """The update listener now actually reloads, so new intervals take effect.

    It used to rewrite the registry by hand and never reload, leaving the old
    interval, timeout and retry count in place until Home Assistant restarted.
    """
    entry = await _setup(hass)
    runtime = hass.data[DOMAIN][entry.entry_id]
    assert runtime.coordinators[PRIORITY_FAST].update_interval.total_seconds() == 60

    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, CONF_SCANINTERVAL: 90, CONF_INTERVAL_MEDIUM: 600,
                 CONF_INTERVAL_SLOW: 1800},
    )
    await hass.async_block_till_done()

    reloaded = hass.data[DOMAIN][entry.entry_id]
    assert reloaded.coordinators[PRIORITY_FAST].update_interval.total_seconds() == 90
    assert reloaded.coordinators[PRIORITY_MEDIUM].update_interval.total_seconds() == 600
    assert reloaded.coordinators[PRIORITY_SLOW].update_interval.total_seconds() == 1800


async def test_unload_removes_the_coordinator(hass):
    """Unloading cleans up after itself."""
    entry = await _setup(hass)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.data[DOMAIN]


async def test_writeable_time_of_day_becomes_a_time_entity(hass):
    """Writeable TimeOfDay datapoints were discovered and then silently dropped.

    api.py classified them as a "time" HAType that no platform claimed, so between
    0.4.0 and 0.5.0 they produced no entity at all and nothing said so.
    """
    await _setup(hass)

    state = _state(hass, "time", STANDBY_START)
    assert state.state == "06:30:00"
    assert state.attributes["icon"] == "mdi:clock-outline"


async def test_an_unreadable_time_is_unknown(hass):
    """An undocumented wire format must not become a plausible but wrong time."""
    datapoints = copy.deepcopy(DATAPOINTS)
    for datapoint in datapoints:
        if datapoint["Id"] == "1970":
            datapoint["Id"] = "1963"  # a datapoint whose value is the "----" sentinel

    await _setup(hass, datapoints=datapoints)

    assert _state(hass, "time", STANDBY_START).state == "unknown"


async def test_setting_a_time_writes_it_in_the_reported_shape(hass):
    """The write matches how the device renders its own reading."""
    from datetime import time as dt_time
    from unittest.mock import AsyncMock, patch

    entry = await _setup(hass)
    entity_id = _entity_id(hass, "time", STANDBY_START)

    with patch(
        "custom_components.siemens_ozw672.api.SiemensOzw672ApiClient.async_write_data",
        new_callable=AsyncMock,
    ) as write:
        await hass.services.async_call(
            "time", "set_value",
            {"entity_id": entity_id, "time": dt_time(21, 45)},
            blocking=True,
        )

    # The reading is "06:30", so the write carries no seconds either.
    assert write.await_args.args[1] == "21:45"
    assert write.await_args.args[0]["Id"] == "1970"
    assert entry.entry_id in hass.data[DOMAIN]


async def test_the_time_domain_can_be_switched_off(hass):
    """The new domain has its own toggle like the other five."""
    await _setup(hass, options={"time": False})

    assert _entity_id(hass, "time", STANDBY_START) is None
