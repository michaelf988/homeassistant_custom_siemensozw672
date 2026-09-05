"""Binary sensor platform for Siemens OZW672."""
import logging

from homeassistant.components.binary_sensor import BinarySensorEntity

from .const import BINARY_SENSOR
from .const import BINARY_SENSOR_DEVICE_CLASS
from .const import DOMAIN
from .entity import SiemensOzw672Entity
from .helpers import dp_configs_for_hatype, platform_enabled

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Setup binary sensor platform."""
    if not platform_enabled(entry, BINARY_SENSOR):
        _LOGGER.debug("BINARY SENSOR - domain disabled in options, adding no entities")
        return
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SiemensOzw672BinarySensor(coordinator, dp_config)
        for dp_config in dp_configs_for_hatype(entry, "binarysensor")
    ]
    _LOGGER.debug(f"BINARY SENSOR Adding {len(entities)} entities")
    async_add_entities(entities)


class SiemensOzw672BinarySensor(SiemensOzw672Entity, BinarySensorEntity):
    """siemens_ozw672 binary_sensor class."""

    _attr_device_class = BINARY_SENSOR_DEVICE_CLASS

    @property
    def is_on(self):
        """Return true if the binary_sensor is on, or None when there is no reading.

        The device's no-data sentinel used to compare unequal to "On" and so read
        as a confident Off.
        """
        value = self._raw_value
        if value is None:
            return None
        return value == "On"
