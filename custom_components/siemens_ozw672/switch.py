"""Switch platform for Siemens OZW672."""
import logging

from homeassistant.components.switch import SwitchEntity
from .const import DOMAIN
from .const import ICON_SWITCH
from .const import SWITCH
from .entity import SiemensOzw672Entity
from .helpers import dp_configs_for_hatype, platform_enabled

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Setup switch platform."""
    if not platform_enabled(entry, SWITCH):
        _LOGGER.debug("SWITCH - domain disabled in options, adding no entities")
        return
    runtime = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SiemensOzw672BinarySwitch(runtime.coordinator_for(dp_config["priority"]), dp_config)
        for dp_config in dp_configs_for_hatype(entry, "switch")
    ]
    _LOGGER.debug(f"SWITCH Adding {len(entities)} entities")
    async_add_entities(entities)


class SiemensOzw672BinarySwitch(SiemensOzw672Entity, SwitchEntity):
    """siemens_ozw672 switch class."""

    _attr_icon = ICON_SWITCH

    @property
    def is_on(self):
        """Return true if the switch is on, or None when there is no reading."""
        value = self._raw_value
        if value is None:
            return None
        return value == "On"

    async def async_turn_on(self, **kwargs):  # pylint: disable=unused-argument
        """Turn on the switch."""
        await self._async_write("1")

    async def async_turn_off(self, **kwargs):  # pylint: disable=unused-argument
        """Turn off the switch."""
        await self._async_write("0")

    async def _async_write(self, value: str) -> None:
        """Write a value and read this datapoint back, so the state is the device's."""
        item = self.config_entry["Id"]
        opline = self.config_entry["OpLine"]
        name = self.config_entry["Name"]
        _LOGGER.info(
            f'SiemensOzw672BinarySwitch - Will update ID/Opline/Name: {item}/{opline}/{name} to Value: {value}'
        )
        # The device echoes the text, not the index that was written.
        await self.async_write_value(value, expected="On" if value == "1" else "Off")
