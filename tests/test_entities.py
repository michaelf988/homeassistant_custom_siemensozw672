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


def _dp(id, opline, name, dptype, hatype, **descr):
    return {
        "Id": id,
        "WriteAccess": "true" if hatype in ("switch", "select", "number") else "false",
        "OpLine": opline,
        "Name": name,
        "MenuItem": "Diagnostics",
        "DPDescr": {"Type": dptype, "HAType": hatype, **descr},
    }


DATAPOINTS = [
    _dp("1960", "39", "Outside temp", "Numeric", "sensor", DecimalDigits="1"),
    # The device reports "----" for this one: no reading at all.
    _dp("1963", "44", "Flow temp", "Numeric", "sensor", DecimalDigits="1"),
    _dp("1961", "40", "Energy total", "Numeric", "sensor", DecimalDigits="0"),
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
]


def _entry(hass, datapoints=None, options=None):
    """A config entry pointed at the built-in "test" host, so no network is used."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONF_VERSION,
        minor_version=CONF_MINOR_VERSION,
        entry_id="entity_entry",
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


async def test_every_platform_produces_its_entities(hass):
    """One datapoint of each shape ends up in the right domain."""
    await _setup(hass)

    assert hass.states.get("sensor.outside_temp") is not None
    assert hass.states.get("sensor.energy_total") is not None
    assert hass.states.get("number.energy_setpoint") is not None
    assert hass.states.get("number.dhw_setpoint") is not None
    assert hass.states.get("switch.dhw_operating_mode") is not None
    assert hass.states.get("select.dhw_release") is not None
    assert hass.states.get("binary_sensor.heat_circuit_pump_1") is not None


async def test_writeable_energy_entity_renders(hass):
    """SiemensOzw672EnergyControl used to raise NameError: ICON_POWER.

    The class referenced ICON_POWER without importing it, so reading the state of
    a writeable kWh datapoint blew up.
    """
    await _setup(hass)

    state = hass.states.get("number.energy_setpoint")
    assert state.state == "120.0"
    assert state.attributes["icon"] == "mdi:lightning-bolt"
    assert state.attributes["unit_of_measurement"] == "kWh"
    assert state.attributes["device_class"] == "energy"


async def test_decimals_are_not_truncated(hass):
    """A reading of " 15.8" stays 15.8 rather than being truncated to 15."""
    assert (await _setup(hass)) is not None

    assert hass.states.get("sensor.outside_temp").state == "15.8"


async def test_missing_reading_is_unknown_not_zero(hass):
    """The device's "----" sentinel must not be recorded as a real zero."""
    await _setup(hass)

    assert hass.states.get("sensor.flow_temp").state == "unknown"


async def test_descriptions_without_min_max_do_not_break_number_entities(hass):
    """A description missing Min/Max/Resolution/DecimalDigits used to raise KeyError."""
    datapoints = copy.deepcopy(DATAPOINTS)
    for datapoint in datapoints:
        if datapoint["Id"] == "1439":
            datapoint["DPDescr"] = {"Type": "Numeric", "HAType": "number"}

    await _setup(hass, datapoints=datapoints)

    state = hass.states.get("number.dhw_setpoint")
    assert state.state == "52.0"
    assert state.attributes["min"] == 0.0
    assert state.attributes["max"] == 100.0
    assert state.attributes["step"] == 1.0


async def test_select_options_come_from_the_description(hass):
    """The enum list drives the options and the current value is one of them."""
    await _setup(hass)

    state = hass.states.get("select.dhw_release")
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

    state = hass.states.get("select.dhw_release")
    assert state.attributes["options"] == []
    # The reported value is not a known option, so it is not claimed as the state.
    assert state.state == "unknown"


async def test_disabled_domain_creates_no_entities(hass):
    """The five domain toggles were stored in the options and never read."""
    await _setup(hass, options={"switch": False})

    assert hass.states.get("switch.dhw_operating_mode") is None
    assert hass.states.get("sensor.outside_temp") is not None


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
    entity = registry.async_get("sensor.outside_temp")
    assert entity.unique_id == "entity_entry_39"


async def test_changing_options_reloads_the_entry(hass):
    """The update listener now actually reloads, so a new scan interval takes effect.

    It used to rewrite the registry by hand and never reload, leaving the old
    interval, timeout and retry count in place until Home Assistant restarted.
    """
    entry = await _setup(hass)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.update_interval.total_seconds() == 60

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "scaninterval": 300}
    )
    await hass.async_block_till_done()

    assert hass.data[DOMAIN][entry.entry_id].update_interval.total_seconds() == 300


async def test_unload_removes_the_coordinator(hass):
    """Unloading cleans up after itself."""
    entry = await _setup(hass)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.entry_id not in hass.data[DOMAIN]
