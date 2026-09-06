"""Tests for the siemens_ozw672 options flow.

Home Assistant made OptionsFlow.config_entry a read-only property, so the previous
pattern of assigning `self.config_entry = config_entry` in __init__ raised

    AttributeError: property 'config_entry' of 'SiemensOzw672OptionsFlowHandler'
    object has no setter

which made the options dialog impossible to open.

The dialog now opens on a menu: connection/interval settings on one branch, the
per-datapoint polling priorities on the other.
"""
import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.siemens_ozw672.const import (
    CONF_DATAPOINTS,
    CONF_HTTPRETRIES,
    CONF_HTTPTIMEOUT,
    CONF_INTERVAL_MEDIUM,
    CONF_INTERVAL_SLOW,
    CONF_PRIORITY,
    CONF_PRIORITY_FAST,
    CONF_PRIORITY_MEDIUM,
    CONF_REQUEST_DELAY,
    CONF_SCANINTERVAL,
    CONF_USE_DEVICE_LONGNAME,
    CONF_VERIFY_SSL,
    DEFAULT_HTTPRETRIES,
    DEFAULT_HTTPTIMEOUT,
    DEFAULT_INTERVAL_MEDIUM,
    DEFAULT_INTERVAL_SLOW,
    DEFAULT_SCANINTERVAL,
    DOMAIN,
    MIN_SCANINTERVAL,
    PRIORITY_FAST,
    PRIORITY_MEDIUM,
    PRIORITY_SLOW,
)

EXISTING_OPTIONS = {
    CONF_HTTPTIMEOUT: 30,
    CONF_HTTPRETRIES: 4,
    CONF_SCANINTERVAL: 120,
    CONF_INTERVAL_MEDIUM: 300,
    CONF_INTERVAL_SLOW: 900,
    CONF_REQUEST_DELAY: 0.0,
    CONF_USE_DEVICE_LONGNAME: True,
    CONF_VERIFY_SSL: False,
    "switch": True,
    "select": True,
    "number": True,
    "binary_sensor": True,
    "sensor": True,
}

SETTINGS_INPUT = {
    CONF_HTTPTIMEOUT: 30,
    CONF_HTTPRETRIES: 4,
    CONF_SCANINTERVAL: 120,
    CONF_INTERVAL_MEDIUM: 300,
    CONF_INTERVAL_SLOW: 900,
    CONF_REQUEST_DELAY: 0.0,
    CONF_USE_DEVICE_LONGNAME: True,
    CONF_VERIFY_SSL: False,
    "switch": True,
    "select": True,
    "number": True,
    "binary_sensor": True,
    "sensor": True,
}

DATAPOINTS = [
    {"Id": "1960", "OpLine": "39", "Name": "Outside temp", "MenuItem": "Diagnostics",
     "WriteAccess": "false", "DPDescr": {"Type": "Numeric", "HAType": "sensor"},
     CONF_PRIORITY: PRIORITY_MEDIUM},
    {"Id": "1439", "OpLine": "3516", "Name": "DHW setpoint", "MenuItem": "DHW",
     "WriteAccess": "true", "DPDescr": {"Type": "Numeric", "HAType": "number"},
     CONF_PRIORITY: PRIORITY_SLOW},
]


def _add_entry(hass, options, datapoints=None):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DATAPOINTS: datapoints if datapoints is not None else DATAPOINTS},
        options=options,
        entry_id="test_options_entry",
    )
    entry.add_to_hass(hass)
    return entry


async def _open_branch(hass, entry, branch):
    """Open the options dialog and follow one menu branch."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"next_step_id": branch}
    )


async def test_options_flow_opens_on_a_menu(hass):
    """The dialog opens instead of raising AttributeError."""
    entry = _add_entry(hass, EXISTING_OPTIONS)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {"settings", "priorities", "datapoints"}


async def test_settings_branch_saves_changes(hass):
    """Submitting the settings form writes the new options back to the entry."""
    entry = _add_entry(hass, EXISTING_OPTIONS)

    result = await _open_branch(hass, entry, "settings")
    assert result["step_id"] == "settings"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={**SETTINGS_INPUT, CONF_SCANINTERVAL: 300}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SCANINTERVAL] == 300


async def test_settings_branch_with_no_existing_options(hass):
    """An entry saved before options existed falls back to the defaults.

    This is the path that reads self.config_entry, so it also guards the property
    access that previously happened in __init__.
    """
    entry = _add_entry(hass, {})

    result = await _open_branch(hass, entry, "settings")

    assert result["type"] is FlowResultType.FORM
    schema_defaults = {str(key): key.default() for key in result["data_schema"].schema}
    assert schema_defaults[CONF_HTTPTIMEOUT] == DEFAULT_HTTPTIMEOUT
    assert schema_defaults[CONF_HTTPRETRIES] == DEFAULT_HTTPRETRIES
    assert schema_defaults[CONF_SCANINTERVAL] == DEFAULT_SCANINTERVAL
    assert schema_defaults[CONF_INTERVAL_MEDIUM] == DEFAULT_INTERVAL_MEDIUM
    assert schema_defaults[CONF_INTERVAL_SLOW] == DEFAULT_INTERVAL_SLOW


async def test_intervals_are_rejected_below_the_minimum(hass):
    """A scan interval of 0 turned the coordinator into a tight polling loop."""
    entry = _add_entry(hass, EXISTING_OPTIONS)

    result = await _open_branch(hass, entry, "settings")

    with pytest.raises(vol.Invalid):
        result["data_schema"]({**SETTINGS_INPUT, CONF_SCANINTERVAL: 0})
    # The lowest accepted value still validates.
    result["data_schema"]({**SETTINGS_INPUT, CONF_SCANINTERVAL: MIN_SCANINTERVAL})


async def test_priorities_branch_preselects_the_current_tiers(hass):
    """Reopening the form shows what each datapoint is currently assigned to."""
    entry = _add_entry(hass, EXISTING_OPTIONS)

    result = await _open_branch(hass, entry, "priorities")

    assert result["step_id"] == "priorities"
    defaults = {str(key): key.default() for key in result["data_schema"].schema}
    assert defaults[CONF_PRIORITY_FAST] == []
    assert defaults[CONF_PRIORITY_MEDIUM] == ["1960"]


async def test_priorities_branch_rewrites_the_datapoints(hass):
    """The chosen tiers are written into entry.data, where the coordinators read them."""
    entry = _add_entry(hass, EXISTING_OPTIONS)

    result = await _open_branch(hass, entry, "priorities")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_PRIORITY_FAST: ["1439"], CONF_PRIORITY_MEDIUM: []},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    stored = {dp["Id"]: dp[CONF_PRIORITY] for dp in entry.data[CONF_DATAPOINTS]}
    assert stored == {"1439": PRIORITY_FAST, "1960": PRIORITY_SLOW}


async def test_unselected_datapoints_fall_to_the_slow_tier(hass):
    """Selecting nothing is the safe default for a device with limited capacity."""
    entry = _add_entry(hass, EXISTING_OPTIONS)

    result = await _open_branch(hass, entry, "priorities")
    await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_PRIORITY_FAST: [], CONF_PRIORITY_MEDIUM: []}
    )
    await hass.async_block_till_done()

    assert all(dp[CONF_PRIORITY] == PRIORITY_SLOW for dp in entry.data[CONF_DATAPOINTS])


async def test_a_datapoint_in_both_lists_counts_as_fast(hass):
    """The stricter tier wins, so a double selection cannot slow a datapoint down."""
    entry = _add_entry(hass, EXISTING_OPTIONS)

    result = await _open_branch(hass, entry, "priorities")
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_PRIORITY_FAST: ["1960"], CONF_PRIORITY_MEDIUM: ["1960"]},
    )
    await hass.async_block_till_done()

    stored = {dp["Id"]: dp[CONF_PRIORITY] for dp in entry.data[CONF_DATAPOINTS]}
    assert stored["1960"] == PRIORITY_FAST


# --- removing datapoints --------------------------------------------------

async def test_configured_datapoints_are_all_ticked_to_start_with(hass):
    """The screen is about removing, so everything starts kept."""
    entry = _add_entry(hass, EXISTING_OPTIONS)

    result = await _open_branch(hass, entry, "datapoints")

    assert result["step_id"] == "datapoints"
    assert result["description_placeholders"] == {"count": "2"}
    defaults = {str(key): key.default() for key in result["data_schema"].schema}
    assert set(defaults[CONF_DATAPOINTS]) == {"1960", "1439"}


async def test_unticking_a_datapoint_removes_it(hass):
    """Disabling an entity does not stop its datapoint being polled; this does."""
    entry = _add_entry(hass, EXISTING_OPTIONS)

    result = await _open_branch(hass, entry, "datapoints")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_DATAPOINTS: ["1960"]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [dp["Id"] for dp in entry.data[CONF_DATAPOINTS]] == ["1960"]


async def test_keeping_everything_changes_nothing(hass):
    """Opening the screen and pressing OK is not a way to lose datapoints."""
    entry = _add_entry(hass, EXISTING_OPTIONS)

    result = await _open_branch(hass, entry, "datapoints")
    await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_DATAPOINTS: ["1960", "1439"]}
    )
    await hass.async_block_till_done()

    assert len(entry.data[CONF_DATAPOINTS]) == 2


async def test_removing_every_datapoint_is_allowed(hass):
    """An entry with nothing to poll must not blow up on the next reload."""
    entry = _add_entry(hass, EXISTING_OPTIONS)

    result = await _open_branch(hass, entry, "datapoints")
    await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_DATAPOINTS: []}
    )
    await hass.async_block_till_done()

    assert entry.data[CONF_DATAPOINTS] == []
