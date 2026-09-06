"""Number platform for Siemens OZW672."""
import logging

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.exceptions import HomeAssistantError

from .api import SiemensOzw672ApiError
from .const import DOMAIN
from .const import ICON_NUMERIC
from .const import ICON_PERCENT
from .const import ICON_POWER
from .const import ICON_THERMOMETER
from .const import NUMBER
from .entity import SiemensOzw672Entity
from .helpers import (
    datapoint_unit,
    decimal_digits,
    descr_float,
    dp_configs_for_hatype,
    parse_numeric,
    platform_enabled,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)

TEMPERATURE_UNITS = {
    "°C": UnitOfTemperature.CELSIUS,
    "°F": UnitOfTemperature.FAHRENHEIT,
    "K": UnitOfTemperature.KELVIN,
}

# Fallbacks for datapoints whose description does not carry Min/Max/Resolution.
# These used to be subscripted directly, so a description without them raised
# KeyError inside the entity properties.
DEFAULT_MIN = 0.0
DEFAULT_MAX = 100.0
DEFAULT_STEP = 1.0


async def async_setup_entry(hass, entry, async_add_entities):
    """Setup number platform."""
    if not platform_enabled(entry, NUMBER):
        _LOGGER.debug("NUMBER - domain disabled in options, adding no entities")
        return
    runtime = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for dp_config in dp_configs_for_hatype(entry, "number"):
        coordinator = runtime.coordinator_for(dp_config["priority"])
        # The stored description decides the class; at setup no poll has run yet.
        data = (coordinator.data or {}).get(dp_config["Id"], {}).get("Data", {})
        unit = datapoint_unit(dp_config, data)
        _LOGGER.debug(f"NUMBER Adding Entity with config: {dp_config}")
        if unit in TEMPERATURE_UNITS:
            entities.append(SiemensOzw672TempControl(coordinator, dp_config))
        elif unit == "%":
            entities.append(SiemensOzw672PercentControl(coordinator, dp_config))
        elif unit in ("kWh", "Wh", "kW", "W"):
            entities.append(SiemensOzw672EnergyControl(coordinator, dp_config))
        else:
            entities.append(SiemensOzw672NumberControl(coordinator, dp_config))

    async_add_entities(entities)


class SiemensOzw672NumberControlBase(SiemensOzw672Entity, NumberEntity):
    """Shared behaviour for the writeable numeric datapoints.

    Note there is deliberately no `state` property here. Overriding it on a
    NumberEntity bypasses Home Assistant's own unit handling, and the old
    implementation did an unguarded float() that raised ValueError for any
    non-numeric reading.
    """

    @property
    def native_value(self):
        """Return the reading, or None when the device reports no data."""
        return parse_numeric(self._dp_data.get("Value"))

    @property
    def suggested_display_precision(self):
        """Decimal places to display, taken from the datapoint description."""
        return decimal_digits(self.config_entry)

    @property
    def native_min_value(self) -> float:
        """Return the lowest value the OZW672 accepts for this datapoint."""
        return descr_float(self.config_entry, "Min", DEFAULT_MIN)

    @property
    def native_max_value(self) -> float:
        """Return the highest value the OZW672 accepts for this datapoint."""
        return descr_float(self.config_entry, "Max", DEFAULT_MAX)

    @property
    def native_step(self) -> float:
        """Return step/resolution."""
        step = descr_float(self.config_entry, "Resolution", DEFAULT_STEP)
        # A resolution of 0 would make Home Assistant's step arithmetic divide by
        # zero; the device reports it for datapoints it does not constrain.
        return step if step and step > 0 else DEFAULT_STEP

    async def async_set_native_value(self, value: float) -> None:
        """Round to the datapoint's precision and write it to the OZW672."""
        item = self.config_entry["Id"]
        opline = self.config_entry["OpLine"]
        name = self.config_entry["Name"]
        existing_value = self._raw_value

        decimals = decimal_digits(self.config_entry)
        if decimals is None or decimals <= 0:
            new_value = round(float(value))
        else:
            new_value = round(float(value), decimals)

        _LOGGER.info(
            f'{type(self).__name__} - Will update ID/Opline/Name: {item}/{opline}/{name} '
            f'to Value: {new_value} from Value: {existing_value}'
        )
        try:
            await self.coordinator.api.async_write_data(self.config_entry, str(new_value))
        except SiemensOzw672ApiError as exception:
            raise HomeAssistantError(
                f"Could not write {name} on the OZW672: {exception}"
            ) from exception
        await self.coordinator.async_request_refresh()


class SiemensOzw672TempControl(SiemensOzw672NumberControlBase):

    _attr_icon = ICON_THERMOMETER
    _attr_device_class = NumberDeviceClass.TEMPERATURE

    @property
    def native_unit_of_measurement(self):
        """Return the native_unit_of_measurement of the sensor."""
        return TEMPERATURE_UNITS.get(
            self._raw_unit or datapoint_unit(self.config_entry),
            UnitOfTemperature.CELSIUS,
        )


class SiemensOzw672PercentControl(SiemensOzw672NumberControlBase):

    _attr_icon = ICON_PERCENT
    _attr_native_unit_of_measurement = PERCENTAGE


class SiemensOzw672EnergyControl(SiemensOzw672NumberControlBase):
    """A writeable energy or power datapoint - typically a meter reading.

    This class used to reference ICON_POWER without importing it (NameError on
    every state read) and set SensorDeviceClass.ENERGY plus a state_class, neither
    of which belongs to the number domain.
    """

    _attr_icon = ICON_POWER

    @property
    def device_class(self) -> NumberDeviceClass | None:
        """Energy and power have distinct number device classes."""
        if self._raw_unit in ("kWh", "Wh"):
            return NumberDeviceClass.ENERGY
        if self._raw_unit in ("kW", "W"):
            return NumberDeviceClass.POWER
        return None

    @property
    def native_unit_of_measurement(self):
        """Return the native_unit_of_measurement of the sensor."""
        return self._raw_unit or datapoint_unit(self.config_entry) or None


class SiemensOzw672NumberControl(SiemensOzw672NumberControlBase):

    _attr_icon = ICON_NUMERIC

    @property
    def native_unit_of_measurement(self):
        """Return whatever unit the device reports, if any."""
        return self._raw_unit or datapoint_unit(self.config_entry) or None
