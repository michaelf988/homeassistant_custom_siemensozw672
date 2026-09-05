"""SiemensOzw672Entity class"""
import logging

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION
from .const import DOMAIN
from .const import MANUFACTURER
from .const import VERSION
from .helpers import clean_value

_LOGGER: logging.Logger = logging.getLogger(__package__)


class SiemensOzw672Entity(CoordinatorEntity):
    def __init__(self, coordinator, config_entry):
        super().__init__(coordinator)
        self.config_entry = config_entry
        _LOGGER.debug(f"SiemensOzw672Entity - config_entry: {config_entry}")

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return self.config_entry["entry_id"]

    @property
    def name(self):
        """Return the name of the entity."""
        return f'{self.config_entry["entity_prefix"]}{self.config_entry["Name"]}'

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.config_entry["device_id"])},
            "name": self.config_entry["device_name"],
            "manufacturer": MANUFACTURER,
            "model": self.config_entry.get("device_model") or None,
            "sw_version": VERSION,
        }

    @property
    def available(self) -> bool:
        """Whether the last poll actually returned a value for this datapoint.

        Without this, a datapoint missing from the coordinator's data raised
        KeyError inside every state property. api.py now skips datapoints it
        could not read instead of failing the whole poll, so this is how a single
        unreadable datapoint shows up: one unavailable entity, not fifty.
        """
        if not super().available:
            return False
        return self.config_entry["Id"] in (self.coordinator.data or {})

    @property
    def _dp_data(self) -> dict:
        """The Data block the last poll returned for this datapoint."""
        return (self.coordinator.data or {}).get(self.config_entry["Id"], {}).get("Data", {})

    @property
    def _raw_value(self):
        """The reported value with padding stripped, or None for the no-data sentinel."""
        return clean_value(self._dp_data.get("Value"))

    @property
    def _raw_unit(self):
        """The reported unit with padding stripped."""
        return str(self._dp_data.get("Unit", "")).strip()

    @property
    def extra_state_attributes(self):
        """Return the state attributes.

        Was named device_state_attributes, which Home Assistant stopped calling in
        0.109, and read coordinator.data.get("id") - a key that never exists,
        because coordinator.data is keyed by datapoint id.
        """
        return {
            "attribution": ATTRIBUTION,
            "id": str(self.config_entry["Id"]),
            "opline": str(self.config_entry.get("OpLine", "")),
            "integration": DOMAIN,
        }
