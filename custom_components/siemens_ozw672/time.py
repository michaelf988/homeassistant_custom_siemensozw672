"""Time platform for Siemens OZW672.

Covers writeable TimeOfDay datapoints - the switching times of the controller's
programmes. Between 0.4.0 and 0.5.0 these had nowhere to go: the API client
classified them as a "time" HAType that no platform claimed, so they were
discovered and then silently dropped.
"""
import logging
from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from .const import DOMAIN
from .const import ICON_TIME
from .const import TIME
from .entity import SiemensOzw672Entity
from .helpers import (
    dp_configs_for_hatype,
    format_time,
    parse_time,
    platform_enabled,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Setup time platform."""
    if not platform_enabled(entry, TIME):
        _LOGGER.debug("TIME - domain disabled in options, adding no entities")
        return
    runtime = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SiemensOzw672TimeControl(runtime.coordinator_for(dp_config["priority"]), dp_config)
        for dp_config in dp_configs_for_hatype(entry, "time")
    ]
    _LOGGER.debug(f"TIME Adding {len(entities)} entities")
    async_add_entities(entities)


class SiemensOzw672TimeControl(SiemensOzw672Entity, TimeEntity):
    """A writeable time of day, e.g. the start of a heating programme."""

    _attr_icon = ICON_TIME

    @property
    def native_value(self) -> dt_time | None:
        """Return the time the device reports, or None if it is unreadable.

        An unparseable reading shows as unknown rather than as a plausible but
        wrong time - the wire format is undocumented and varies by firmware.
        """
        return parse_time(self._dp_data.get("Value"))

    async def async_set_value(self, value: dt_time) -> None:
        """Write a new time to the OZW672."""
        item = self.config_entry["Id"]
        opline = self.config_entry["OpLine"]
        name = self.config_entry["Name"]
        existing = self._raw_value

        # Match the shape the device reported, rather than always sending seconds.
        new_value = format_time(value, existing)
        _LOGGER.info(
            f'SiemensOzw672TimeControl - Will update ID/Opline/Name: {item}/{opline}/{name} '
            f'to Value: {new_value} from Value: {existing}'
        )
        await self.async_write_value(new_value, expected=new_value)
