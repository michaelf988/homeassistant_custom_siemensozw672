"""SelectEntity platform for Siemens OZW672."""
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError

from .api import SiemensOzw672ApiError
from .const import DOMAIN
from .const import ICON_SELECT
from .const import SELECT
from .entity import SiemensOzw672Entity
from .helpers import dp_configs_for_hatype, platform_enabled

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Setup select platform."""
    if not platform_enabled(entry, SELECT):
        _LOGGER.debug("SELECT - domain disabled in options, adding no entities")
        return
    runtime = hass.data[DOMAIN][entry.entry_id]

    entities = [
        SiemensOzw672SelectControl(runtime.coordinator_for(dp_config["priority"]), dp_config)
        for dp_config in dp_configs_for_hatype(entry, "select")
    ]
    _LOGGER.debug(f"SELECT Adding {len(entities)} entities")
    async_add_entities(entities)


class SiemensOzw672SelectControl(SiemensOzw672Entity, SelectEntity):

    _attr_icon = ICON_SELECT

    @property
    def _enums(self) -> list[dict]:
        """The enumeration entries discovered from the datapoint description."""
        return (self.config_entry.get("DPDescr") or {}).get("Enums") or []

    @property
    def options(self) -> list[str]:
        """Return the option list from the Enums discovered from the datapoint description.

        Order follows the device's own list. The previous implementation built a
        dict keyed by int(Value) purely to drop duplicates, which also meant a
        datapoint whose description carried no Enums raised KeyError.
        """
        seen: list[str] = []
        for enum in self._enums:
            text = enum.get("Text")
            if text is not None and text not in seen:
                seen.append(text)
        return seen

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state.

        Returns None for a reported value that is not one of the options, which
        Home Assistant would otherwise reject with an "invalid option" error.
        """
        value = self._raw_value
        if value is None:
            return None
        if value not in self.options:
            _LOGGER.debug(
                "Datapoint %s reports %r, which is not one of its known options %s",
                self.config_entry["Id"], value, self.options,
            )
            return None
        return value

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.debug(f'SiemensOzw672SelectControl - select_option String: {option}')
        item = self.config_entry["Id"]
        opline = self.config_entry["OpLine"]
        name = self.config_entry["Name"]

        enum_value = next(
            (enum.get("Value") for enum in self._enums if enum.get("Text") == option),
            None,
        )
        if enum_value is None:
            raise HomeAssistantError(
                f"{option!r} is not a known option for {name} on the OZW672"
            )

        _LOGGER.info(
            f'SiemensOzw672SelectControl - Will update ID/Opline/Name: {item}/{opline}/{name} to Value: {enum_value}'
        )
        try:
            await self.coordinator.api.async_write_data(self.config_entry, enum_value)
        except SiemensOzw672ApiError as exception:
            raise HomeAssistantError(
                f"Could not write {name} on the OZW672: {exception}"
            ) from exception
        await self.coordinator.async_request_refresh()
