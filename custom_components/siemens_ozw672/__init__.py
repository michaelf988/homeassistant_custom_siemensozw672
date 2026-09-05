"""
Custom integration to integrate Siemens OZW672 with Home Assistant.
For more details about this integration, please refer to
https://github.com/johnaherninfotrack/homeassistant_custom_siemensozw672
"""
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
from .const import CONF_SCANINTERVAL
from .const import CONF_USERNAME
from .const import CONF_USE_DEVICE_LONGNAME
from .const import CONF_VERIFY_SSL
from .const import CONF_VERSION
from .const import DEFAULT_HTTPRETRIES
from .const import DEFAULT_HTTPTIMEOUT
from .const import DEFAULT_OPTIONS
from .const import DEFAULT_SCANINTERVAL
from .const import DEFAULT_VERIFY_SSL
from .const import DOMAIN
from .const import MAX_HTTPRETRIES
from .const import MAX_HTTPTIMEOUT
from .const import MAX_SCANINTERVAL
from .const import MIN_HTTPRETRIES
from .const import MIN_HTTPTIMEOUT
from .const import MIN_SCANINTERVAL
from .const import PLATFORMS
from .const import STARTUP_MESSAGE
from .helpers import option_int

_LOGGER: logging.Logger = logging.getLogger(__package__)


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
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    _LOGGER.debug("STARTUP - Setting up config entry %s", entry.entry_id)
    conf_scaninterval = option_int(
        entry, CONF_SCANINTERVAL, DEFAULT_SCANINTERVAL, MIN_SCANINTERVAL, MAX_SCANINTERVAL
    )
    datapoints = entry.data.get(CONF_DATAPOINTS)

    client = _build_client(hass, entry)
    coordinator = SiemensOzw672DataUpdateCoordinator(
        hass,
        client=client,
        datapoints=datapoints,
        scaninterval=timedelta(seconds=conf_scaninterval),
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_migrate_entry(hass, entry: ConfigEntry):
    """Bring an older config entry up to the current schema."""
    if entry.version == CONF_VERSION and entry.minor_version == CONF_MINOR_VERSION:
        return True
    _LOGGER.debug("Upgrading OZW Configuration")
    try:
        client = _build_client(hass, entry)
        # Add new attribute - DeviceLongName if not exists
        _LOGGER.debug(f'Migrating existing data: {entry.data}')
        if entry.data.get(CONF_DEVICE_LONGNAME) is None:
            sysinfo = await _get_sysinfo(client)  # Gets the serial # of the OZW
            deviceid = entry.data.get(CONF_DEVICE_ID)  # DeviceID has serial number of OZW and RVS
            discovereddevices = await _get_devices(client)
            for dd in discovereddevices or []:
                dd_serial = f'{sysinfo["SerialNr"]}:{dd["SerialNr"]}'
                if dd_serial == deviceid:
                    name_string = f'{dd["Addr"]} {dd["Type"]}'
                    _data = dict(entry.data)
                    _data[CONF_DEVICE_LONGNAME] = name_string
                    _options = dict(entry.options)
                    if _options == {}:
                        _options = dict(DEFAULT_OPTIONS)
                    else:
                        _options[CONF_USE_DEVICE_LONGNAME] = False

                    hass.config_entries.async_update_entry(
                        entry, title=f"{entry.data.get(CONF_DEVICE)}", data=_data, options=_options
                    )
                    break
        datapoints = entry.data.get(CONF_DATAPOINTS) or []
        all_dpdata = await client.async_get_data(datapoints)
        all_dpdescr = await client.async_get_data_descr(datapoints, all_dpdata, True)
        newdatapoints = []
        for dpjson in datapoints:
            descr_response = all_dpdescr.get(dpjson["Id"])
            if descr_response is None:
                # The datapoint could not be read during migration. Carry it over
                # unchanged rather than dropping it: a transient read failure must
                # not silently delete the user's entity.
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
        _data = {**entry.data}
        _data[CONF_DATAPOINTS] = newdatapoints
        hass.config_entries.async_update_entry(
            entry, data=_data, minor_version=CONF_MINOR_VERSION, version=CONF_VERSION
        )
        _LOGGER.debug("Config Check Complete")
        return True
    except Exception as exception:  # pylint: disable=broad-except
        _LOGGER.error(f'Config Check Failed: {repr(exception)}')
        return False


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
    ) -> None:
        """Initialize."""
        self.api = client
        self.platforms = []
        self.datapoints = datapoints
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=scaninterval)

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
