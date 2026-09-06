"""Walk the whole config flow against the built-in TESTDATA device.

Nothing covered the flow before. It now ends on a priority step, because polling
every selected datapoint at the same rate is what makes a large selection painful
on a controller this small.
"""
from unittest.mock import patch

import pytest

from homeassistant.data_entry_flow import FlowResultType

from homeassistant.helpers import selector

from custom_components.siemens_ozw672.const import (
    CONF_DATAPOINTS,
    CONF_GO_BACK,
    CONF_SELECT_ALL,
    CONF_DEVICE,
    CONF_HOST,
    CONF_MENUITEMS,
    CONF_MINOR_VERSION,
    CONF_PASSWORD,
    CONF_PRIORITY,
    CONF_PRIORITY_FAST,
    CONF_PRIORITY_MEDIUM,
    CONF_PROTOCOL,
    CONF_USERNAME,
    CONF_VERSION,
    DOMAIN,
    PRIORITY_FAST,
    PRIORITY_MEDIUM,
    PRIORITY_SLOW,
)


def _selector(result, key):
    """The selector for one field of the shown form."""
    for schema_key in result["data_schema"].schema:
        if str(schema_key) == key:
            return result["data_schema"].schema[schema_key]
    raise AssertionError(f"{key} is not on this form: {list(result['data_schema'].schema)}")


def _options(result, key):
    """The SelectSelector choices offered for one field of the shown form."""
    return _selector(result, key).config["options"]


def _fields(result):
    return {str(key) for key in result["data_schema"].schema}


def _value_with(result, key, needle):
    """The option value whose label contains `needle`."""
    for option in _options(result, key):
        if needle in option["label"]:
            return option["value"]
    raise AssertionError(f"no {key} option labelled like {needle!r}")


async def _walk_to_priorities(hass, datapoints=None):
    """Drive the flow up to, but not through, the priority step."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PROTOCOL: "http", CONF_HOST: "test",
         CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
    )
    assert result["step_id"] == "device"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DEVICE: _value_with(result, CONF_DEVICE, "RVS43"),
         "use_device_longname": False,
         "prefix_with_function": False,
         "prefix_with_opline": False},
    )
    assert result["step_id"] == "mainmenu"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MENUITEMS: [_value_with(result, CONF_MENUITEMS, "DHW")]},
    )
    assert result["step_id"] == "submenu"

    # The DHW menu holds three datapoints and no submenus.
    offered = [option["value"] for option in _options(result, CONF_DATAPOINTS)]
    assert len(offered) == 3
    if datapoints == "all":
        return await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_SELECT_ALL: True}
        )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DATAPOINTS: offered}
    )


async def test_the_flow_ends_on_the_priority_step(hass):
    """Discovery is followed by the tier assignment, not by creating the entry."""
    result = await _walk_to_priorities(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "priorities"
    assert result["description_placeholders"] == {"count": "3"}
    labels = [option["label"] for option in _options(result, CONF_PRIORITY_FAST)]
    assert any("DHW operating mode" in label for label in labels)


async def test_chosen_priorities_are_stored_on_the_datapoints(hass):
    """Each tier reaches the config entry, where the coordinators read it."""
    result = await _walk_to_priorities(hass)
    fast = _value_with(result, CONF_PRIORITY_FAST, "DHW temperature nominal setpoint")
    medium = _value_with(result, CONF_PRIORITY_MEDIUM, "DHW operating mode")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PRIORITY_FAST: [fast], CONF_PRIORITY_MEDIUM: [medium]},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    stored = {dp["Name"]: dp[CONF_PRIORITY] for dp in result["data"][CONF_DATAPOINTS]}
    assert stored == {
        "DHW temperature nominal setpoint": PRIORITY_FAST,
        "DHW operating mode": PRIORITY_MEDIUM,
        # Not picked, so it lands in the slowest tier - the safe default.
        "DHW release": PRIORITY_SLOW,
    }


async def test_a_new_entry_is_written_at_the_current_schema_version(hass):
    """An entry created today must not look like one that needs migrating."""
    result = await _walk_to_priorities(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRIORITY_FAST: [], CONF_PRIORITY_MEDIUM: []}
    )
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert (entry.version, entry.minor_version) == (CONF_VERSION, CONF_MINOR_VERSION)


async def test_picking_nothing_leaves_everything_in_the_slow_tier(hass):
    """Zero clicks is the gentlest possible configuration for the device."""
    result = await _walk_to_priorities(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRIORITY_FAST: [], CONF_PRIORITY_MEDIUM: []}
    )

    assert all(dp[CONF_PRIORITY] == PRIORITY_SLOW for dp in result["data"][CONF_DATAPOINTS])


async def test_bad_credentials_do_not_advance(hass):
    """A device that rejects the login keeps the user on the first form.

    The login is patched rather than pointed at an unroutable address: Home
    Assistant's test harness blocks real socket use, so the address version of
    this test failed on the socket rather than on the credentials.
    """
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    with patch(
        "custom_components.siemens_ozw672.api.SiemensOzw672ApiClient.async_get_sessionid",
        return_value=False,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PROTOCOL: "http", CONF_HOST: "ozw.example",
             CONF_USERNAME: "user", CONF_PASSWORD: "wrong"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "auth"}


async def test_datapoints_carry_a_priority_even_if_the_step_is_skipped(hass):
    """Defensive: the entity layer must never see a datapoint without a tier."""
    result = await _walk_to_priorities(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRIORITY_MEDIUM: []}
    )

    assert all(CONF_PRIORITY in dp for dp in result["data"][CONF_DATAPOINTS])
    assert all(dp[CONF_PRIORITY] != PRIORITY_MEDIUM for dp in result["data"][CONF_DATAPOINTS])


# --- checkbox lists -------------------------------------------------------

@pytest.mark.parametrize(
    ("step", "field"),
    [("mainmenu", CONF_MENUITEMS), ("submenu", CONF_DATAPOINTS)],
)
async def test_selection_forms_render_as_checkbox_lists(hass, step, field):
    """A dropdown hides every option behind a search field.

    SelectSelectorMode.LIST is what makes the frontend draw checkboxes instead.
    """
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PROTOCOL: "http", CONF_HOST: "test",
         CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DEVICE: _value_with(result, CONF_DEVICE, "RVS43"),
         "use_device_longname": False, "prefix_with_function": False,
         "prefix_with_opline": False},
    )
    if step == "submenu":
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_MENUITEMS: [_value_with(result, CONF_MENUITEMS, "DHW")]},
        )

    assert result["step_id"] == step
    config = _selector(result, field).config
    # The config normalises the enum to its string value.
    assert config["mode"] == selector.SelectSelectorMode.LIST
    assert config["multiple"] is True


async def test_the_priority_form_is_a_checkbox_list_too(hass):
    """Sorting datapoints into tiers is the same kind of picking."""
    result = await _walk_to_priorities(hass)

    assert _selector(result, CONF_PRIORITY_FAST).config["mode"] == selector.SelectSelectorMode.LIST


# --- select all -----------------------------------------------------------

async def test_select_all_takes_everything_offered(hass):
    """Home Assistant has no select-all, so the flow interprets one itself."""
    result = await _walk_to_priorities(hass, datapoints="all")

    # All three DHW datapoints were taken without listing them.
    assert result["description_placeholders"] == {"count": "3"}


async def test_select_all_wins_over_an_empty_selection(hass):
    """Ticking select-all and picking nothing still selects everything."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_PROTOCOL: "http", CONF_HOST: "test",
         CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_DEVICE: _value_with(result, CONF_DEVICE, "RVS43"),
         "use_device_longname": False, "prefix_with_function": False,
         "prefix_with_opline": False},
    )
    offered = len(_options(result, CONF_MENUITEMS))
    assert offered > 1

    # Every main menu item, without naming one of them.
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MENUITEMS: [], CONF_SELECT_ALL: True}
    )

    assert result["step_id"] == "submenu"


# --- going back -----------------------------------------------------------

async def test_going_back_from_priorities_returns_to_the_datapoint_form(hass):
    """The only way to revisit a step used to be aborting and starting over."""
    result = await _walk_to_priorities(hass)
    assert result["step_id"] == "priorities"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GO_BACK: True}
    )

    assert result["step_id"] == "submenu"
    # The same form, with the same three datapoints still on offer.
    assert len(_options(result, CONF_DATAPOINTS)) == 3


async def test_going_back_discards_what_that_step_collected(hass):
    """Otherwise a revisit would append the datapoints a second time."""
    result = await _walk_to_priorities(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GO_BACK: True}
    )

    # Re-select a single datapoint this time.
    one = _options(result, CONF_DATAPOINTS)[0]["value"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DATAPOINTS: [one]}
    )

    assert result["step_id"] == "priorities"
    assert result["description_placeholders"] == {"count": "1"}


async def test_going_back_twice_reaches_the_main_menu(hass):
    """Back is a stack, not a single step."""
    result = await _walk_to_priorities(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GO_BACK: True}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GO_BACK: True}
    )

    assert result["step_id"] == "mainmenu"


async def test_back_at_the_first_step_says_so(hass):
    """Rather than aborting the flow or silently doing nothing."""
    result = await _walk_to_priorities(hass)
    for _ in range(2):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_GO_BACK: True}
        )
    assert result["step_id"] == "mainmenu"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GO_BACK: True}
    )

    assert result["step_id"] == "mainmenu"
    assert result["errors"] == {"base": "no_previous_step"}


async def test_the_flow_still_completes_after_going_back(hass):
    """Back must leave the flow in a state that can still finish."""
    result = await _walk_to_priorities(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GO_BACK: True}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SELECT_ALL: True}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PRIORITY_FAST: [], CONF_PRIORITY_MEDIUM: []}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(result["data"][CONF_DATAPOINTS]) == 3
