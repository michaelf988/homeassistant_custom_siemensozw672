"""Walk the whole config flow against the built-in TESTDATA device.

Nothing covered the flow before. Polling tiers are now chosen on the same screen
as the datapoints themselves, because sorting a couple of hundred of them on one
closing screen is not a thing anyone wants to do.
"""
from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import selector

from custom_components.siemens_ozw672.const import (
    CONF_DATAPOINTS,
    CONF_DATAPOINTS_BY_PRIORITY,
    CONF_DEVICE,
    CONF_GO_BACK,
    CONF_HOST,
    CONF_MENUITEMS,
    CONF_MINOR_VERSION,
    CONF_PASSWORD,
    CONF_PRIORITY,
    CONF_PROTOCOL,
    CONF_SELECT_ALL,
    CONF_SELECT_REST_SLOW,
    CONF_USERNAME,
    CONF_VERSION,
    DOMAIN,
    PRIORITY_FAST,
    PRIORITY_MEDIUM,
    PRIORITY_SLOW,
)

FAST = CONF_DATAPOINTS_BY_PRIORITY[PRIORITY_FAST]
MEDIUM = CONF_DATAPOINTS_BY_PRIORITY[PRIORITY_MEDIUM]
SLOW = CONF_DATAPOINTS_BY_PRIORITY[PRIORITY_SLOW]


def _selector(result, key):
    """The selector for one field of the shown form."""
    for schema_key in result["data_schema"].schema:
        if str(schema_key) == key:
            return result["data_schema"].schema[schema_key]
    raise AssertionError(f"{key} is not on this form: {list(result['data_schema'].schema)}")


def _options(result, key):
    """The SelectSelector choices offered for one field of the shown form."""
    return _selector(result, key).config["options"]


def _value_with(result, key, needle):
    """The option value whose label contains `needle`."""
    for option in _options(result, key):
        if needle in option["label"]:
            return option["value"]
    raise AssertionError(f"no {key} option labelled like {needle!r}")


async def _walk_to_datapoints(hass):
    """Drive the flow to the DHW datapoint screen."""
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
    return result


def _stored(result):
    return {dp["Name"]: dp[CONF_PRIORITY] for dp in result["data"][CONF_DATAPOINTS]}


# --- the value preview ----------------------------------------------------

async def test_datapoints_are_offered_with_their_current_value(hass):
    """A datapoint with no reading costs a request per poll forever.

    Seeing that before picking it is the whole point: the OZW672 reports "----"
    for plenty of datapoints that simply do not apply to a given plant.
    """
    result = await _walk_to_datapoints(hass)

    labels = {option["label"] for option in _options(result, FAST)}
    assert any("DHW operating mode — On" in label for label in labels)
    assert any("DHW temperature nominal setpoint — 52 °C" in label for label in labels)
    # The one the device has no value for is called out rather than looking normal.
    assert any("DHW no reading — (no value)" in label for label in labels)


async def test_the_preview_is_not_fetched_twice(hass):
    """The readings shown on the form are reused for the selection itself."""
    result = await _walk_to_datapoints(hass)
    chosen = _value_with(result, FAST, "DHW operating mode")

    with patch(
        "custom_components.siemens_ozw672.config_flow."
        "SiemensOzw672FlowHandler._get_data"
    ) as reread:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {FAST: [chosen]}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    # The form already read them to build its labels.
    reread.assert_not_called()


# --- tiers on the selection screen ----------------------------------------

async def test_every_tier_is_offered_on_the_datapoint_screen(hass):
    """One checkbox list per tier - Home Assistant has no per-row radio group."""
    result = await _walk_to_datapoints(hass)

    for field in (FAST, MEDIUM, SLOW):
        config = _selector(result, field).config
        assert config["mode"] == selector.SelectSelectorMode.LIST
        assert config["multiple"] is True
        assert len(config["options"]) == 4


async def test_the_tier_is_taken_from_the_list_it_was_ticked_in(hass):
    """The flow no longer ends on a screen listing every datapoint again."""
    result = await _walk_to_datapoints(hass)
    fast = _value_with(result, FAST, "DHW temperature nominal setpoint")
    medium = _value_with(result, MEDIUM, "DHW operating mode")
    slow = _value_with(result, SLOW, "DHW release")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {FAST: [fast], MEDIUM: [medium], SLOW: [slow]}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _stored(result) == {
        "DHW temperature nominal setpoint": PRIORITY_FAST,
        "DHW operating mode": PRIORITY_MEDIUM,
        "DHW release": PRIORITY_SLOW,
    }


async def test_unticked_datapoints_are_not_taken_at_all(hass):
    """Not choosing a tier means not monitoring it, not monitoring it slowly."""
    result = await _walk_to_datapoints(hass)
    fast = _value_with(result, FAST, "DHW operating mode")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {FAST: [fast]}
    )

    assert list(_stored(result)) == ["DHW operating mode"]


async def test_the_rest_can_be_taken_at_the_slowest_tier(hass):
    """Tick the few that need to be current, then sweep up the remainder."""
    result = await _walk_to_datapoints(hass)
    fast = _value_with(result, FAST, "DHW operating mode")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {FAST: [fast], CONF_SELECT_REST_SLOW: True}
    )

    stored = _stored(result)
    assert len(stored) == 4
    assert stored["DHW operating mode"] == PRIORITY_FAST
    assert stored["DHW release"] == PRIORITY_SLOW


# --- the logic check ------------------------------------------------------

async def test_a_datapoint_in_two_tiers_is_rejected(hass):
    """Exactly one tier each; guessing which the user meant would be wrong."""
    result = await _walk_to_datapoints(hass)
    both = _value_with(result, FAST, "DHW operating mode")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {FAST: [both], MEDIUM: [both]}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "submenu"
    assert result["errors"] == {"base": "duplicate_priority"}


async def test_the_rejected_screen_can_be_corrected_and_submitted(hass):
    """The error is a correction, not a dead end."""
    result = await _walk_to_datapoints(hass)
    both = _value_with(result, FAST, "DHW operating mode")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {FAST: [both], MEDIUM: [both]}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {FAST: [both]}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert _stored(result) == {"DHW operating mode": PRIORITY_FAST}


async def test_the_same_datapoint_in_all_three_is_rejected_too(hass):
    """Not just the two-list case."""
    result = await _walk_to_datapoints(hass)
    both = _value_with(result, FAST, "DHW release")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {FAST: [both], MEDIUM: [both], SLOW: [both]}
    )

    assert result["errors"] == {"base": "duplicate_priority"}


# --- the rest of the flow -------------------------------------------------

async def test_a_new_entry_is_written_at_the_current_schema_version(hass):
    """An entry created today must not look like one that needs migrating."""
    result = await _walk_to_datapoints(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SELECT_REST_SLOW: True}
    )
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert (entry.version, entry.minor_version) == (CONF_VERSION, CONF_MINOR_VERSION)


async def test_the_main_menu_is_a_checkbox_list_with_select_all(hass):
    """Same treatment as the datapoint screen."""
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

    assert _selector(result, CONF_MENUITEMS).config["mode"] == selector.SelectSelectorMode.LIST
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MENUITEMS: [], CONF_SELECT_ALL: True}
    )
    assert result["step_id"] == "submenu"


async def test_going_back_returns_to_the_main_menu(hass):
    """Home Assistant has no back navigation, so the flow keeps its own history."""
    result = await _walk_to_datapoints(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GO_BACK: True}
    )

    assert result["step_id"] == "mainmenu"


async def test_back_at_the_first_step_says_so(hass):
    """Rather than aborting the flow or silently doing nothing."""
    result = await _walk_to_datapoints(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GO_BACK: True}
    )
    assert result["step_id"] == "mainmenu"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GO_BACK: True}
    )

    assert result["step_id"] == "mainmenu"
    assert result["errors"] == {"base": "no_previous_step"}


async def test_going_back_discards_what_that_screen_collected(hass):
    """Otherwise a revisit would take the datapoints a second time."""
    result = await _walk_to_datapoints(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_SELECT_REST_SLOW: True, CONF_GO_BACK: True}
    )
    assert result["step_id"] == "mainmenu"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_MENUITEMS: [_value_with(result, CONF_MENUITEMS, "DHW")]},
    )
    one = _value_with(result, FAST, "DHW operating mode")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {FAST: [one]}
    )

    assert len(result["data"][CONF_DATAPOINTS]) == 1


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


@pytest.mark.parametrize("field", [FAST, MEDIUM, SLOW])
async def test_every_stored_datapoint_carries_a_tier(hass, field):
    """The entity layer must never see a datapoint without one."""
    result = await _walk_to_datapoints(hass)
    one = _value_with(result, field, "DHW release")

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {field: [one]}
    )

    assert all(CONF_PRIORITY in dp for dp in result["data"][CONF_DATAPOINTS])
