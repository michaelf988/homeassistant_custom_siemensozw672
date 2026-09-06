"""SiemensOzw672Entity class"""
import logging

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import SiemensOzw672ApiError
from .const import ATTRIBUTION
from .const import DOMAIN
from .const import MANUFACTURER
from .const import VERSION
from .helpers import clean_value, readings_match

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

    async def async_write_value(self, value: str, expected=None) -> None:
        """Write to the device, then re-read this one datapoint straight away.

        Refreshing the coordinator instead re-reads every datapoint of the tier
        and publishes nothing until all of them are in, so a setting in a large
        slow tier took minutes to show whether it had taken. This reads back the
        single datapoint that was written, which is one request.

        `expected` is what the datapoint should read afterwards. The OZW672
        accepts some writes and then ignores them, so a mismatch is worth saying
        out loud rather than leaving the user to spot it.
        """
        name = self.config_entry["Name"]
        try:
            await self.coordinator.api.async_write_data(self.config_entry, value)
        except SiemensOzw672ApiError as exception:
            raise HomeAssistantError(
                f"Could not write {name} on the OZW672: {exception}"
            ) from exception

        reading = await self.coordinator.async_refresh_datapoint(self.config_entry)
        if expected is None or reading is None:
            return
        actual = clean_value(reading.get("Data", {}).get("Value"))
        if not readings_match(expected, actual):
            _LOGGER.warning(
                "The OZW672 accepted the write to %s but still reports %r instead of "
                "%r. This device ignores some writes; check the datapoint in its own "
                "web interface.",
                name, actual, expected,
            )

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
