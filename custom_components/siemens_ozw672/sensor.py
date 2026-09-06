"""Sensor platform for Siemens OZW672."""
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
)

from .const import DOMAIN
from .const import ICON
from .const import ICON_NUMERIC
from .const import ICON_PERCENT
from .const import ICON_POWER
from .const import ICON_THERMOMETER
from .const import SENSOR
from .entity import SiemensOzw672Entity
from .helpers import (
    datapoint_type,
    datapoint_unit,
    decimal_digits,
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


async def async_setup_entry(hass, entry, async_add_entities):
    """Setup sensor platform."""
    if not platform_enabled(entry, SENSOR):
        _LOGGER.debug("SENSOR - domain disabled in options, adding no entities")
        return
    runtime = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for dp_config in dp_configs_for_hatype(entry, "sensor"):
        coordinator = runtime.coordinator_for(dp_config["priority"])
        # Read from the stored description first: at setup the first poll has
        # deliberately not run yet, so coordinator.data is still empty.
        data = (coordinator.data or {}).get(dp_config["Id"], {}).get("Data", {})
        dptype = datapoint_type(dp_config, data)
        unit = datapoint_unit(dp_config, data)
        _LOGGER.debug(f"SENSOR Adding Entity with config: {dp_config}")
        if dptype == "Numeric" and unit in TEMPERATURE_UNITS:
            entities.append(SiemensOzw672TempSensor(coordinator, dp_config))
        elif dptype == "Numeric" and unit == "%":
            entities.append(SiemensOzw672PercentSensor(coordinator, dp_config))
        elif dptype == "Numeric" and unit in ("kWh", "Wh"):
            entities.append(SiemensOzw672EnergySensor(coordinator, dp_config))
        elif dptype == "Numeric" and unit in ("kW", "W"):
            entities.append(SiemensOzw672PowerSensor(coordinator, dp_config))
        elif dptype == "Numeric":
            entities.append(SiemensOzw672NumberSensor(coordinator, dp_config))
        else:
            # All unknown data types will produce a read only sensor
            entities.append(SiemensOzw672Sensor(coordinator, dp_config))

    # One call instead of one per datapoint: async_add_entities was previously
    # invoked inside the loop, which makes Home Assistant do the whole entity
    # registration dance once per entity.
    async_add_entities(entities)


class SiemensOzw672Sensor(SiemensOzw672Entity, SensorEntity):
    """Read-only fallback sensor for datapoint types with no dedicated class.

    Most of these are enumerations reporting text such as "Boost heating", so the
    value is passed through as-is. The device's no-data sentinel becomes None.
    """

    _attr_icon = ICON

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._raw_value


class SiemensOzw672NumericSensor(SiemensOzw672Entity, SensorEntity):
    """Shared behaviour for the numeric read-only sensors."""

    @property
    def native_value(self):
        """Return the reading, or None when the device reports no data."""
        return parse_numeric(self._dp_data.get("Value"))

    @property
    def suggested_display_precision(self):
        """Decimal places to display, taken from the datapoint description."""
        return decimal_digits(self.config_entry)


class SiemensOzw672TempSensor(SiemensOzw672NumericSensor):

    _attr_icon = ICON_THERMOMETER
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_unit_of_measurement(self):
        """Return the native_unit_of_measurement of the sensor."""
        return TEMPERATURE_UNITS.get(
            self._raw_unit or datapoint_unit(self.config_entry),
            UnitOfTemperature.CELSIUS,
        )


class SiemensOzw672PercentSensor(SiemensOzw672NumericSensor):

    _attr_icon = ICON_PERCENT
    _attr_native_unit_of_measurement = PERCENTAGE
    # There is no percentage device class; the unit alone is correct. The previous
    # "siemens_ozw672__percent_device_class" was a legacy custom device class
    # string, which modern Home Assistant rejects.
    _attr_device_class = None
    _attr_state_class = SensorStateClass.MEASUREMENT


class SiemensOzw672EnergySensor(SiemensOzw672NumericSensor):

    _attr_icon = ICON_POWER
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def native_unit_of_measurement(self):
        """Return the native_unit_of_measurement of the sensor."""
        return self._raw_unit or datapoint_unit(self.config_entry) or None


class SiemensOzw672PowerSensor(SiemensOzw672NumericSensor):

    _attr_icon = ICON_POWER
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_unit_of_measurement(self):
        """Return the native_unit_of_measurement of the sensor."""
        return self._raw_unit or datapoint_unit(self.config_entry) or None


class SiemensOzw672NumberSensor(SiemensOzw672NumericSensor):

    _attr_icon = ICON_NUMERIC
    # None, because a generic numeric datapoint has no specific class. The previous
    # "siemens_ozw672__number_device_class" was a legacy custom device class string,
    # which modern Home Assistant rejects.
    _attr_device_class = None
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_unit_of_measurement(self):
        """Return the unit the device reports, e.g. bar, h or min.

        This class covers every numeric datapoint that is not a temperature,
        percentage, energy or power reading, and it used to drop the unit
        entirely - a pressure sensor showed a bare number. No device class is set,
        so Home Assistant accepts whatever string the OZW672 reports.
        """
        return self._raw_unit or datapoint_unit(self.config_entry) or None
