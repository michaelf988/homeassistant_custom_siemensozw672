"""
Custom integration to integrate Siemens OZW672 with Home Assistant.

A fork of johnaherninfotrack/homeassistant_custom_siemensozw672. For more details,
please refer to https://github.com/michaelf988/homeassistant_custom_siemensozw672
"""
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SiemensOzw672ApiClient, SiemensOzw672ApiError
from .const import CONF_DATAPOINTS
from .const import CONF_DEVICE
from .const import CONF_DEVICE_ID
from .const import CONF_DEVICE_LONGNAME
from .const import CONF_HOST
from .const import CONF_HTTPRETRIES
from .const import CONF_HTTPTIMEOUT
from .const import CONF_MINOR_VERSION
from .const import CONF_PASSWORD
from .const import CONF_PROTOCOL
from .const import CONF_PRIORITY
from .const import CONF_REQUEST_DELAY
from .const import CONF_USERNAME
from .const import CONF_USE_DEVICE_LONGNAME
from .const import CONF_VERIFY_SSL
from .const import CONF_VERSION
from .const import DEFAULT_HTTPRETRIES
from .const import DEFAULT_HTTPTIMEOUT
from .const import DEFAULT_OPTIONS
from .const import DEFAULT_PRIORITY
from .const import DEFAULT_REQUEST_DELAY
from .const import DEFAULT_VERIFY_SSL
from .const import DOMAIN
from .const import MAX_HTTPRETRIES
from .const import MAX_REQUEST_DELAY
from .const import MAX_HTTPTIMEOUT
from .const import MAX_SCANINTERVAL
from .const import MIN_HTTPRETRIES
from .const import MIN_HTTPTIMEOUT
from .const import MIN_SCANINTERVAL
from .const import PRIORITY_INTERVAL_OPTIONS
from .const import PLATFORMS
from .const import STARTUP_MESSAGE
from .helpers import group_datapoints_by_priority, option_int

_LOGGER: logging.Logger = logging.getLogger(__package__)

# This integration is configured entirely through the UI. Declaring that explicitly
# is what hassfest asks for from anything that implements async_setup(), and it makes
# Home Assistant reject a stray YAML block instead of silently ignoring it.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType):
    """Set up this integration using YAML is not supported."""
    _async_repair_string_entry_versions(hass)
    return True


def _async_repair_string_entry_versions(hass: HomeAssistant) -> None:
    """Coerce config entry version/minor_version back to int.

    Releases 0.3.6/0.3.7 briefly shipped CONF_VERSION/CONF_MINOR_VERSION as strings,
    so entries created in that window are persisted with string versions. Home
    Assistant's own async_migrate() then does `self.version > handler.VERSION`, which
    raises TypeError: '>' not supported between instances of 'str' and 'int' before
    async_migrate_entry() ever runs - leaving affected users unable to load the
    integration at all (issue #39).

    async_setup() runs before config entries are migrated, so this is our only chance
    to repair the stored values.
    """
    for entry in hass.config_entries.async_entries(DOMAIN):
        version = entry.version
        minor_version = entry.minor_version
        if isinstance(version, int) and isinstance(minor_version, int):
            continue
        try:
            new_version = int(version)
            new_minor_version = int(minor_version)
        except (TypeError, ValueError):
            _LOGGER.error(
                "Config entry %s has an unparseable version (%r.%r) and cannot be "
                "repaired automatically; please remove and re-add the integration",
                entry.entry_id, version, minor_version,
            )
            continue
        _LOGGER.warning(
            "Repairing config entry %s with string version %r.%r -> %d.%d (issue #39)",
            entry.entry_id, version, minor_version, new_version, new_minor_version,
        )
        hass.config_entries.async_update_entry(
            entry, version=new_version, minor_version=new_minor_version
        )


def _build_client(hass: HomeAssistant, entry: ConfigEntry) -> SiemensOzw672ApiClient:
    """Create an API client configured from the entry's data and options."""
    conf_httptimeout = option_int(
        entry, CONF_HTTPTIMEOUT, DEFAULT_HTTPTIMEOUT, MIN_HTTPTIMEOUT, MAX_HTTPTIMEOUT
    )
    conf_httpretries = option_int(
        entry, CONF_HTTPRETRIES, DEFAULT_HTTPRETRIES, MIN_HTTPRETRIES, MAX_HTTPRETRIES
    )
    verify_ssl = bool(entry.options.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL))
    try:
        request_delay = float(entry.options.get(CONF_REQUEST_DELAY, DEFAULT_REQUEST_DELAY))
    except (TypeError, ValueError):
        request_delay = DEFAULT_REQUEST_DELAY
    request_delay = max(0.0, min(MAX_REQUEST_DELAY, request_delay))
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    return SiemensOzw672ApiClient(
        entry.data.get(CONF_HOST),
        entry.data.get(CONF_PROTOCOL),
        entry.data.get(CONF_USERNAME),
        entry.data.get(CONF_PASSWORD),
        session,
        timeout=conf_httptimeout,
        retries=conf_httpretries,
        verify_ssl=verify_ssl,
        request_delay=request_delay,
    )


@dataclass
class SiemensOzw672Runtime:
    """What a loaded config entry keeps in hass.data.

    One API client shared by every tier - it serialises all traffic through a
    single lock, which is the whole point on a device this small - and one
    coordinator per polling tier that actually has datapoints.
    """

    client: SiemensOzw672ApiClient
    coordinators: dict = field(default_factory=dict)

    def coordinator_for(self, priority: str):
        """The coordinator polling this priority, falling back to any that exists."""
        if priority in self.coordinators:
            return self.coordinators[priority]
        if DEFAULT_PRIORITY in self.coordinators:
            return self.coordinators[DEFAULT_PRIORITY]
        return next(iter(self.coordinators.values()))


def _interval_for(entry: ConfigEntry, priority: str) -> int:
    """The poll interval configured for one priority tier, in seconds."""
    option, default = PRIORITY_INTERVAL_OPTIONS[priority]
    return option_int(entry, option, default, MIN_SCANINTERVAL, MAX_SCANINTERVAL)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    _LOGGER.debug("STARTUP - Setting up config entry %s", entry.entry_id)
    client = _build_client(hass, entry)
    runtime = SiemensOzw672Runtime(client=client)

    for priority, tier_datapoints in group_datapoints_by_priority(entry).items():
        interval = _interval_for(entry, priority)
        _LOGGER.debug(
            "Polling %d datapoint(s) at priority %s every %ss",
            len(tier_datapoints), priority, interval,
        )
        runtime.coordinators[priority] = SiemensOzw672DataUpdateCoordinator(
            hass,
            client=client,
            datapoints=tier_datapoints,
            scaninterval=timedelta(seconds=interval),
            priority=priority,
        )

    for coordinator in runtime.coordinators.values():
        await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = runtime

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_migrate_entry(hass, entry: ConfigEntry):
    """Bring an older config entry up to the current schema.

    Each step is applied on its own. The 1.4 -> 1.5 step re-reads every datapoint
    description from the device, which is a lot of traffic for a controller this
    small, so it must not run again just because a later, purely local step was
    added on top of it.
    """
    if entry.version == CONF_VERSION and entry.minor_version == CONF_MINOR_VERSION:
        return True
    _LOGGER.debug(
        "Upgrading OZW configuration from %s.%s to %s.%s",
        entry.version, entry.minor_version, CONF_VERSION, CONF_MINOR_VERSION,
    )
    try:
        data = dict(entry.data)

        if entry.minor_version < 5:
            data = await _migrate_to_1_5(hass, entry, data)

        if entry.minor_version < 6:
            # Assign every datapoint the default polling priority. Purely local -
            # the device is not contacted for this.
            data[CONF_DATAPOINTS] = [
                {**datapoint, CONF_PRIORITY: datapoint.get(CONF_PRIORITY, DEFAULT_PRIORITY)}
                for datapoint in (data.get(CONF_DATAPOINTS) or [])
            ]
            _LOGGER.info(
                "Assigned the '%s' polling priority to %d existing datapoint(s); "
                "you can change this under the integration's options",
                DEFAULT_PRIORITY, len(data[CONF_DATAPOINTS]),
            )

        if entry.minor_version < 7:
            # Re-classify writeable TimeOfDay datapoints. 0.4.0 and 0.5.0 stored them
            # as sensors because no platform claimed the "time" HAType; there is a
            # time platform now. Purely local - the device is not contacted.
            data[CONF_DATAPOINTS] = [
                _reclassify_time_of_day(datapoint)
                for datapoint in (data.get(CONF_DATAPOINTS) or [])
            ]

        hass.config_entries.async_update_entry(
            entry, data=data, minor_version=CONF_MINOR_VERSION, version=CONF_VERSION
        )
        _LOGGER.debug("Config Check Complete")
        return True
    except Exception as exception:  # pylint: disable=broad-except
        _LOGGER.error(f'Config Check Failed: {repr(exception)}')
        return False


def _reclassify_time_of_day(datapoint: dict) -> dict:
    """Promote a writeable TimeOfDay datapoint from sensor to time entity.

    The old sensor entity is left behind in the registry; Home Assistant shows it
    as unavailable and it can be deleted. There is no way to move an entity
    between domains without that.
    """
    descr = datapoint.get("DPDescr") or {}
    if descr.get("Type") != "TimeOfDay" or datapoint.get("WriteAccess") != "true":
        return datapoint
    if descr.get("HAType") == "time":
        return datapoint
    _LOGGER.info(
        "Datapoint %s (%s) is a writeable time of day and becomes a time entity; "
        "its old sensor entity can be deleted",
        datapoint.get("Id"), datapoint.get("Name"),
    )
    return {**datapoint, "DPDescr": {**descr, "HAType": "time"}}


async def _migrate_to_1_5(hass, entry: ConfigEntry, data: dict) -> dict:
    """Add DeviceLongName and re-read every datapoint description from the device."""
    client = _build_client(hass, entry)
    _LOGGER.debug(f'Migrating existing data: {entry.data}')
    if data.get(CONF_DEVICE_LONGNAME) is None:
        sysinfo = await _get_sysinfo(client)  # Gets the serial # of the OZW
        deviceid = data.get(CONF_DEVICE_ID)  # DeviceID has serial number of OZW and RVS
        discovereddevices = await _get_devices(client)
        for dd in discovereddevices or []:
            dd_serial = f'{sysinfo["SerialNr"]}:{dd["SerialNr"]}'
            if dd_serial == deviceid:
                data[CONF_DEVICE_LONGNAME] = f'{dd["Addr"]} {dd["Type"]}'
                _options = dict(entry.options)
                if _options == {}:
                    _options = dict(DEFAULT_OPTIONS)
                else:
                    _options[CONF_USE_DEVICE_LONGNAME] = False
                hass.config_entries.async_update_entry(
                    entry, title=f"{data.get(CONF_DEVICE)}", options=_options
                )
                break

    datapoints = data.get(CONF_DATAPOINTS) or []
    all_dpdata = await client.async_get_data(datapoints)
    all_dpdescr = await client.async_get_data_descr(datapoints, all_dpdata, True)
    newdatapoints = []
    for dpjson in datapoints:
        descr_response = all_dpdescr.get(dpjson["Id"])
        if descr_response is None:
            # The datapoint could not be read. Carry it over unchanged rather than
            # dropping it: a transient read failure must not silently delete the
            # user's entity.
            _LOGGER.warning(
                "Datapoint %s could not be re-read during migration; keeping its "
                "existing configuration", dpjson["Id"],
            )
            newdatapoints.append(dpjson)
            continue
        dpdescr = descr_response["Description"]
        newdatapoints.append({
            "Id": dpjson["Id"],
            "WriteAccess": dpjson["WriteAccess"],
            "OpLine": dpjson["OpLine"],
            "Name": dpdescr.get("Name", dpjson.get("Name")),
            "MenuItem": dpjson["MenuItem"],
            "DPDescr": dpdescr,
        })
    data[CONF_DATAPOINTS] = newdatapoints
    return data


async def _get_sysinfo(client):
    """Return the OZW672 system info, or None if it could not be fetched.

    The `except: pass` this replaces left `info` unbound, so a failed call raised
    UnboundLocalError instead of reporting the real problem.
    """
    try:
        return await client.async_get_sysinfo()
    except SiemensOzw672ApiError as err:
        _LOGGER.debug(f'Exception: {repr(err)}')
        return None


async def _get_devices(client):
    """Return the discovered device list, or None if it could not be fetched."""
    try:
        return await client.async_get_devices()
    except SiemensOzw672ApiError as err:
        _LOGGER.debug(f'Exception: {repr(err)}')
        return None


class SiemensOzw672DataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SiemensOzw672ApiClient,
        datapoints,
        scaninterval,
        priority: str = DEFAULT_PRIORITY,
    ) -> None:
        """Initialize."""
        self.api = client
        self.platforms = []
        self.datapoints = datapoints
        self.priority = priority
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN} ({priority})", update_interval=scaninterval
        )

    async def _async_update_data(self):
        """Update all data via the OZW672 Web API."""
        try:
            return await self.api.async_get_data(self.datapoints)
        except SiemensOzw672ApiError as exception:
            raise UpdateFailed(str(exception)) from exception
        except Exception as exception:  # pylint: disable=broad-except
            _LOGGER.debug(f'Exception: {repr(exception)}')
            raise UpdateFailed(repr(exception)) from exception


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry after its options changed.

    This is the whole listener now. It used to rewrite the device registry and
    entry data by hand but never actually reload, so a changed scan interval,
    timeout or retry count did nothing until Home Assistant was restarted. The
    device and entity names come from the entities' own device_info, which is
    rebuilt on reload.
    """
    await hass.config_entries.async_reload(entry.entry_id)
