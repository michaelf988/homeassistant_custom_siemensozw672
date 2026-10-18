"""The datapoints follow the OZW672 when it renumbers its menu tree.

What happened on a real plant: the OZW672 regenerated its menu tree, every
datapoint got a new Id, and the config entry kept the old ones. Polling went on
under the old Ids, so the return temperature showed a fan speed, the clock showed
a date, two DHW setpoints swapped - and an automation would have written to
whatever datapoint now sat behind the old Id.
"""
import copy
from unittest.mock import patch

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.siemens_ozw672.api import SiemensOzw672ApiClient
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
    CONF_PRIORITY,
    CONF_PROTOCOL,
    CONF_TREESTAMP,
    CONF_USERNAME,
    CONF_VERSION,
    DEFAULT_OPTIONS,
    DOMAIN,
    DP_ADDRESS,
    DP_UNRESOLVED,
    ISSUE_UNRESOLVED,
    PRIORITY_FAST,
    PRIORITY_MEDIUM,
)
from custom_components.siemens_ozw672.helpers import datapoint_identifier
from custom_components.siemens_ozw672.remap import resolve_datapoints, tree_stamp

# TreeDate/TreeTime of the RVS43 in TESTDATA["DEVICELIST"].
TESTDATA_TREESTAMP = "08.06.2023 20:15"

ENTRY_ID = "remap_entry"
DEVICE_ID = "00FD3100033C:008600004EBF"
LONGNAME = "0.1 RVS43.345/109"


def _dp(id, opline, name, menu, dptype, hatype, priority=PRIORITY_MEDIUM, descr_name=None, **descr):
    return {
        "Id": id,
        "WriteAccess": "true" if hatype in ("switch", "select", "number") else "false",
        "OpLine": opline,
        "Name": name,
        "MenuItem": menu,
        CONF_PRIORITY: priority,
        "DPDescr": {"Type": dptype, "HAType": hatype,
                    **({"Name": descr_name} if descr_name else {}), **descr},
    }


def _outside(id="1960", **kw):
    return _dp(id, "39", "Outside temp", "Diagnostics consumer", "Numeric", "sensor",
               priority=PRIORITY_FAST, Unit="°C", DecimalDigits="1", **kw)


def _dhw_setpoint(id="1439", **kw):
    return _dp(id, "3516", "DHW temperature nominal setpoint", "DHW", "Numeric", "number",
               Unit="°C", Min="45.000000", Max="60.000000", Resolution="1.000000",
               DecimalDigits="0", **kw)


def _dhw_release(id="1441", **kw):
    return _dp(id, "3522", "DHW release", "DHW", "Enumeration", "select",
               Enums=[{"Text": "24h/day", "Value": "0"},
                      {"Text": "Heating programs with forward shift", "Value": "1"},
                      {"Text": "Time switch program 4", "Value": "2"}], **kw)


def _entry(hass, datapoints, treestamp=None):
    data = {
        CONF_HOST: "test",
        CONF_PROTOCOL: "http",
        CONF_USERNAME: "user",
        CONF_PASSWORD: "pass",
        CONF_DEVICE: "RVS43",
        CONF_DEVICE_LONGNAME: LONGNAME,
        CONF_DEVICE_ID: DEVICE_ID,
        CONF_DATAPOINTS: copy.deepcopy(datapoints),
        CONF_PREFIX_FUNCTION: False,
        CONF_PREFIX_OPLINE: False,
    }
    if treestamp is not None:
        data[CONF_TREESTAMP] = treestamp
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CONF_VERSION,
        minor_version=CONF_MINOR_VERSION,
        entry_id=ENTRY_ID,
        title="RVS43",
        data=data,
        options={**DEFAULT_OPTIONS, CONF_PREFIX_FUNCTION: False, CONF_PREFIX_OPLINE: False},
    )
    entry.add_to_hass(hass)
    return entry


async def _setup(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    # The first polls run as background tasks, and a remap reloads the entry,
    # which starts new ones; wait for all of that to settle.
    await hass.async_block_till_done(wait_background_tasks=True)
    await hass.async_block_till_done(wait_background_tasks=True)


def _unique_id(hass, opline):
    """The unique id of the configured datapoint with this operating line."""
    entry = hass.config_entries.async_get_entry(ENTRY_ID)
    return f"{ENTRY_ID}_{datapoint_identifier(_stored(entry, opline))}"


def _state(hass, domain, opline):
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, _unique_id(hass, opline))
    return hass.states.get(entity_id) if entity_id else None


def _stored(entry, opline):
    return next(dp for dp in entry.data[CONF_DATAPOINTS] if dp["OpLine"] == opline)


class _MenuCounter:
    """Counts menu tree requests while passing them through to TESTDATA."""

    def __init__(self):
        self.calls = 0
        self._original = SiemensOzw672ApiClient.async_get_menutree

    def __enter__(self):
        counter = self

        async def counted(client, id):
            counter.calls += 1
            return await counter._original(client, id)

        self._patch = patch.object(SiemensOzw672ApiClient, "async_get_menutree", counted)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


# --- the pure matching ---------------------------------------------------------------

MENUS = {
    "DHW": [
        {"Id": "2438", "Address": "0x310571", "DpSubKey": "0", "WriteAccess": "true",
         "Text": {"Id": "3514", "Long": "DHW operating mode"}},
        {"Id": "2439", "Address": "0x3106b9", "DpSubKey": "0", "WriteAccess": "true",
         "Text": {"Id": "3516", "Long": "DHW temperature nominal setpoint"}},
    ],
    "Diagnostics consumer": [
        {"Id": "2960", "Address": "0x50521", "DpSubKey": "0", "WriteAccess": "false",
         "Text": {"Id": "39", "Long": "Outside temp"}},
    ],
}


def test_renumbered_datapoints_get_their_new_ids():
    resolution = resolve_datapoints([_outside(), _dhw_setpoint()], MENUS)

    assert [dp["Id"] for dp in resolution.datapoints] == ["2960", "2439"]
    assert not resolution.unresolved
    assert len(resolution.moved) == 2
    # The bus address is recorded so the next remap can rely on it.
    assert resolution.datapoints[1][DP_ADDRESS] == "0x3106b9"


def test_unchanged_datapoints_report_nothing():
    resolution = resolve_datapoints([_outside(id="2960")], MENUS)

    assert resolution.datapoints[0]["Id"] == "2960"
    assert not resolution.moved and not resolution.unresolved


def test_the_bus_address_wins_over_the_operating_line():
    """Once recorded, the address identifies the datapoint even if the text id moved."""
    datapoint = {**_dhw_setpoint(), DP_ADDRESS: "0x3106b9", "DpSubKey": "0", "OpLine": "1"}

    resolution = resolve_datapoints([datapoint], MENUS)

    assert resolution.datapoints[0]["Id"] == "2439"


def test_a_vanished_menu_leaves_the_datapoint_unresolved():
    resolution = resolve_datapoints([_dhw_setpoint()], {"DHW": None})

    assert resolution.datapoints[0][DP_UNRESOLVED] is True
    assert resolution.datapoints[0]["Id"] == "1439"  # untouched, but no longer polled
    assert len(resolution.unresolved) == 1


def test_an_ambiguous_operating_line_is_settled_by_the_name_or_not_at_all():
    twins = [
        {"Id": "1", "Text": {"Id": "3516", "Long": "DHW temperature nominal setpoint"}},
        {"Id": "2", "Text": {"Id": "3516", "Long": "Something else"}},
    ]
    settled = resolve_datapoints([_dhw_setpoint()], {"DHW": twins})
    assert settled.datapoints[0]["Id"] == "1"

    nameless = [{"Id": "1", "Text": {"Id": "3516", "Long": "A"}},
                {"Id": "2", "Text": {"Id": "3516", "Long": "B"}}]
    unsettled = resolve_datapoints([_dhw_setpoint()], {"DHW": nameless})
    assert unsettled.datapoints[0][DP_UNRESOLVED] is True


def test_two_datapoints_claiming_one_id_are_both_distrusted():
    duplicate = {**_dhw_setpoint(), "Name": "copy"}

    resolution = resolve_datapoints([_dhw_setpoint(), duplicate], MENUS)

    assert all(dp[DP_UNRESOLVED] for dp in resolution.datapoints)


def test_a_previously_unresolved_datapoint_recovers():
    resolution = resolve_datapoints([{**_outside(), DP_UNRESOLVED: True}], MENUS)

    assert DP_UNRESOLVED not in resolution.datapoints[0]


def test_tree_stamp_matches_the_device_by_serial_then_by_name():
    devices = [
        {"Addr": "0.1", "Type": "RVS43.345/109", "SerialNr": "008600004EBF",
         "TreeDate": "08.06.2023", "TreeTime": "20:15"},
    ]
    assert tree_stamp(devices, DEVICE_ID, None) == TESTDATA_TREESTAMP
    assert tree_stamp(devices, None, LONGNAME) == TESTDATA_TREESTAMP
    assert tree_stamp(devices, "x:other", "0.2 Something") is None
    assert tree_stamp([{"SerialNr": "008600004EBF"}], DEVICE_ID, None) is None


# --- end to end against the TESTDATA device ------------------------------------------

async def test_renumbered_tree_is_remapped_on_startup(hass):
    """Stored Ids pointing at the wrong datapoints are corrected before any poll.

    1441 is really "DHW release" and 1439 really the DHW setpoint; the stored
    entry has them swapped, exactly the kind of shift a regenerated tree causes.
    """
    entry = _entry(hass, [_outside(id="7777"), _dhw_setpoint(id="1441"), _dhw_release(id="1439")])

    await _setup(hass, entry)

    assert _stored(entry, "39")["Id"] == "1960"
    assert _stored(entry, "3516")["Id"] == "1439"
    assert _stored(entry, "3522")["Id"] == "1441"
    assert entry.data[CONF_TREESTAMP] == TESTDATA_TREESTAMP
    assert _state(hass, "sensor", "39").state == "15.8"
    assert _state(hass, "number", "3516").state == "52.0"
    assert _state(hass, "select", "3522").state == "24h/day"
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_UNRESOLVED}_{ENTRY_ID}") is None


async def test_unchanged_tree_is_not_walked(hass):
    """With the stored stamp matching, startup costs one device-list request, no menus."""
    entry = _entry(hass, [_outside(), _dhw_setpoint()], treestamp=TESTDATA_TREESTAMP)
    before = copy.deepcopy(dict(entry.data))

    with _MenuCounter() as menus:
        await _setup(hass, entry)

    assert menus.calls == 0
    assert dict(entry.data) == before
    assert _state(hass, "sensor", "39").state == "15.8"


async def test_remap_does_not_loop(hass):
    """The reload a remap triggers finds everything verified and walks nothing."""
    entry = _entry(hass, [_outside(id="7777")])

    with _MenuCounter() as menus:
        await _setup(hass, entry)
        walked = menus.calls
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    assert walked > 0
    assert menus.calls == walked


async def test_unfindable_datapoint_is_neither_polled_nor_written(hass):
    """Unavailable, never showing another datapoint's value, never written to."""
    lost = _dp("1960", "123", "Gone", "No such menu", "Numeric", "number",
               Unit="°C", Min="0", Max="10", Resolution="1", DecimalDigits="0")
    entry = _entry(hass, [lost, _dhw_setpoint()])

    await _setup(hass, entry)

    assert _stored(entry, "123")[DP_UNRESOLVED] is True
    # 1960 is a perfectly readable datapoint - the outside temperature - which is
    # exactly why the stale Id must not be polled for this entity.
    assert _state(hass, "number", "123").state == "unavailable"
    assert _state(hass, "number", "3516").state == "52.0"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"{ISSUE_UNRESOLVED}_{ENTRY_ID}")
    assert issue is not None and "Gone" in issue.translation_placeholders["datapoints"]

    entity_id = er.async_get(hass).async_get_entity_id("number", DOMAIN, _unique_id(hass, "123"))
    with patch.object(SiemensOzw672ApiClient, "async_write_data") as write:
        try:
            await hass.services.async_call(
                "number", "set_value", {"entity_id": entity_id, "value": 5}, blocking=True
            )
        except HomeAssistantError:
            pass
    write.assert_not_called()


async def test_spot_check_catches_a_renumbering_the_stamp_missed(hass):
    """Even with a matching stamp, a datapoint describing itself differently triggers a remap."""
    swapped = _dhw_setpoint(id="1441", descr_name="DHW temperature nominal setpoint")
    entry = _entry(hass, [swapped], treestamp=TESTDATA_TREESTAMP)

    await _setup(hass, entry)
    # The spot check fails the first poll and remaps; the reload polls again.
    await hass.async_block_till_done()

    assert _stored(entry, "3516")["Id"] == "1439"
    assert _state(hass, "number", "3516").state == "52.0"


async def test_lost_connection_rechecks_the_stamp(hass):
    """After a poll in which nothing could be read, the tree stamp is checked again."""
    entry = _entry(hass, [_outside()], treestamp=TESTDATA_TREESTAMP)
    await _setup(hass, entry)
    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime.coordinators[PRIORITY_FAST]

    with patch.object(
        SiemensOzw672ApiClient, "async_get_devices",
        autospec=True, side_effect=SiemensOzw672ApiClient.async_get_devices,
    ) as devices:
        await coordinator.async_refresh()
        assert devices.call_count == 0  # verified already, nothing to check

        runtime.verifier.connection_lost()
        await coordinator.async_refresh()
        assert devices.call_count == 1


async def test_a_new_session_rechecks_the_stamp(hass):
    """The OZW672 dropping our session usually means it restarted - check the tree."""
    entry = _entry(hass, [_outside()], treestamp=TESTDATA_TREESTAMP)
    await _setup(hass, entry)
    runtime = hass.data[DOMAIN][entry.entry_id]

    with patch.object(
        SiemensOzw672ApiClient, "async_get_devices",
        autospec=True, side_effect=SiemensOzw672ApiClient.async_get_devices,
    ) as devices:
        runtime.client.session_generation += 1
        await runtime.coordinators[PRIORITY_FAST].async_refresh()

    assert devices.call_count == 1
