"""Shared helpers for the Siemens OZW672 integration.

The five entity platforms used to carry an identical, copy-pasted 25-line setup
loop. Keeping that logic here means a fix (or a new field such as the polling
priority) has to be made once instead of five times.
"""
from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DATAPOINTS,
    CONF_PRIORITY,
    CONF_DEVICE,
    CONF_DEVICE_LONGNAME,
    CONF_PREFIX_FUNCTION,
    CONF_PREFIX_OPLINE,
    CONF_USE_DEVICE_LONGNAME,
    DEFAULT_PREFIX_FUNCTION,
    DEFAULT_PREFIX_OPLINE,
    DEFAULT_PRIORITY,
    DEFAULT_USE_DEVICE_LONGNAME,
    PRIORITIES,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


def parse_numeric(raw: Any) -> float | None:
    """Parse a numeric reading from the OZW672, or None if it carries no value.

    The device pads values ("       19.8") and reports a run of dashes ("---")
    when a datapoint has no reading. Returning None makes the entity unknown
    rather than inventing a number, which would otherwise be recorded as a real
    measurement in long-term statistics.

    Note this deliberately does not use str.isnumeric(): that returns False for
    "19.8" (the decimal point disqualifies it) and for "-3", which is how
    decimals ended up truncated and sub-1.0 values read as zero.
    """
    text = clean_value(raw)
    if text is None:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def clean_value(raw: Any) -> str | None:
    """Strip the device's padding, or return None for its no-data sentinel.

    The OZW672 reports a run of dashes ("--", "----") for a datapoint it has no
    reading for. api.py used to rewrite that to "0" before it ever reached an
    entity, so a missing reading was recorded as a real zero.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or set(text) == {"-"}:
        return None
    return text


def parse_time(raw: Any) -> time | None:
    """Parse a time-of-day reading, or None if it carries no usable value.

    The exact wire format of a TimeOfDay datapoint is not documented and varies by
    firmware, so both "HH:MM" and "HH:MM:SS" are accepted, with or without the
    padding the device applies to other values. Anything else yields None, which
    shows as unknown rather than as a wrong time.
    """
    text = clean_value(raw)
    if text is None:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    _LOGGER.warning(
        "Could not read %r as a time of day; expected HH:MM or HH:MM:SS", text
    )
    return None


def format_time(value: time, like: Any = None) -> str:
    """Render a time for writing back, matching the shape the device reported.

    Writing "06:30:00" to a datapoint the device reports as "06:30" is the kind of
    thing this hardware rejects silently, so the reading is used as the template.
    """
    reference = clean_value(like) or ""
    if reference.count(":") >= 2:
        return value.strftime("%H:%M:%S")
    return value.strftime("%H:%M")


def datapoint_type(config_entry: dict, data: dict | None = None) -> str:
    """The datapoint's value type, from the stored description if possible."""
    descr = config_entry.get("DPDescr") or {}
    return str(descr.get("Type") or (data or {}).get("Type") or "")


def datapoint_unit(config_entry: dict, data: dict | None = None) -> str:
    """The datapoint's unit, from the stored description if possible.

    The platforms used to read this out of the coordinator's data, which forced
    setup to wait for a complete first poll before it could decide which entity
    class each datapoint gets. Discovery already knows the unit, so it is stored
    in the description; the live reading is only a fallback for entries written
    before that.
    """
    descr = config_entry.get("DPDescr") or {}
    unit = descr.get("Unit")
    if unit is None:
        unit = (data or {}).get("Unit")
    return str(unit or "").strip()


def has_stored_unit(config_entry: dict) -> bool:
    """Whether discovery recorded a unit for this datapoint.

    Distinguishes "the description says there is no unit" (an enumeration) from
    "the description predates units being stored at all", which is the case for
    entries written before 0.8.0.
    """
    return "Unit" in (config_entry.get("DPDescr") or {})


def decimal_digits(config_entry: dict) -> int | None:
    """Display precision from the datapoint description, or None if absent.

    Not every datapoint returns DecimalDigits, so this must not subscript it
    directly - doing so raised KeyError inside the state machinery and silently
    froze the affected entities.
    """
    return descr_int(config_entry, "DecimalDigits")


def descr_float(config_entry: dict, key: str, default: float | None = None) -> float | None:
    """Read a float out of DPDescr, falling back when it is missing or unparseable.

    Min/Max/Resolution are absent for datapoints whose description was never
    fetched, so subscripting them raises KeyError inside the entity properties.
    """
    raw = (config_entry.get("DPDescr") or {}).get(key)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def descr_int(config_entry: dict, key: str, default: int | None = None) -> int | None:
    """Read an int out of DPDescr, falling back when it is missing or unparseable."""
    raw = (config_entry.get("DPDescr") or {}).get(key)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def entry_flag(entry: ConfigEntry, key: str, default: bool) -> bool:
    """Read a boolean setting, preferring options over the copy held in data.

    The config flow writes the naming flags into both entry.data and
    entry.options. Reading options first means a future options screen can change
    them without the stale copy in data winning.
    """
    if key in entry.options:
        return bool(entry.options[key])
    if key in entry.data:
        return bool(entry.data[key])
    return default


def option_int(
    entry: ConfigEntry, key: str, default: int, minimum: int, maximum: int
) -> int:
    """Read a numeric option, clamped into a range that cannot break the poller.

    Stored options are not re-validated when the schema changes, and entries
    written before the options dialog validated its input can hold anything - a
    scan interval of 0 turned the coordinator into a tight polling loop.
    """
    raw = entry.options.get(key)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        _LOGGER.warning(
            "Option %s has the unusable value %r; falling back to %s", key, raw, default
        )
        return default
    clamped = max(minimum, min(maximum, value))
    if clamped != value:
        _LOGGER.warning(
            "Option %s is set to %s, which is outside the supported range "
            "%s-%s; using %s instead",
            key, value, minimum, maximum, clamped,
        )
    return clamped


def device_name(entry: ConfigEntry) -> str:
    """Return the device name the user picked (short name or Addr+Type)."""
    if entry_flag(entry, CONF_USE_DEVICE_LONGNAME, DEFAULT_USE_DEVICE_LONGNAME):
        return entry.data.get(CONF_DEVICE_LONGNAME) or entry.data.get(CONF_DEVICE, "")
    return entry.data.get(CONF_DEVICE, "")


def device_model(entry: ConfigEntry) -> str | None:
    """Best guess at the controller model, e.g. "RVS43.345/109".

    CONF_DEVICE_LONGNAME holds the LPB/BSB address and the type ("0.1 RVS43.345/109");
    the model is the part after the address.
    """
    longname = entry.data.get(CONF_DEVICE_LONGNAME)
    if not longname:
        return None
    parts = str(longname).split(" ", 1)
    return parts[1] if len(parts) == 2 else str(longname)


def platform_enabled(entry: ConfigEntry, platform: str) -> bool:
    """Whether the user left this entity domain switched on in the options.

    These five toggles were shown in the options dialog but never read anywhere,
    so switching a domain off did nothing.
    """
    return entry.options.get(platform, True) is not False


def datapoint_identifier(datapoint: dict) -> str:
    """Stable per-datapoint suffix for the entity unique_id.

    Prefers the operating line number from the manual, because the API's own
    datapoint Id changes whenever the OZW672 regenerates its menu tree. Falls
    back to the API Id when there is no usable operating line.
    """
    try:
        opline = int(datapoint.get("OpLine"))
    except (TypeError, ValueError):
        opline = 0
    if opline > 1:
        return str(datapoint["OpLine"])
    return "00" + str(datapoint.get("Id", ""))


def datapoint_priority(datapoint: dict) -> str:
    """The polling tier this datapoint belongs to.

    Datapoints stored before priorities existed carry no Priority at all, and a
    hand-edited entry could carry nonsense, so anything unrecognised falls back to
    the middle tier rather than dropping the datapoint.
    """
    priority = (datapoint or {}).get(CONF_PRIORITY)
    if priority in PRIORITIES:
        return priority
    return DEFAULT_PRIORITY


def group_datapoints_by_priority(entry: ConfigEntry) -> dict[str, list[dict]]:
    """Split the configured datapoints into one list per polling tier.

    Tiers with no datapoints are left out entirely, so no coordinator is created
    for them and the device is never polled for an empty list.
    """
    grouped: dict[str, list[dict]] = {}
    for datapoint in entry.data.get(CONF_DATAPOINTS) or []:
        grouped.setdefault(datapoint_priority(datapoint), []).append(datapoint)
    return grouped


def build_dp_configs(entry: ConfigEntry) -> list[dict]:
    """Return the runtime config for every configured datapoint.

    Each entry is a *copy*. The platforms used to write their runtime keys
    (entry_id, device_id, device_name, entity_prefix) straight back into the
    dicts inside entry.data["datapoints"], so setting up an entity mutated - and
    eventually persisted - the stored config entry as a side effect.
    """
    prefix_function = entry_flag(entry, CONF_PREFIX_FUNCTION, DEFAULT_PREFIX_FUNCTION)
    prefix_opline = entry_flag(entry, CONF_PREFIX_OPLINE, DEFAULT_PREFIX_OPLINE)
    name = device_name(entry)
    model = device_model(entry)

    configs: list[dict] = []
    for datapoint in entry.data.get(CONF_DATAPOINTS) or []:
        dp_config = dict(datapoint)
        dp_config["entry_id"] = f"{entry.entry_id}_{datapoint_identifier(datapoint)}"
        dp_config["device_id"] = entry.entry_id
        dp_config["device_name"] = name
        dp_config["device_model"] = model
        dp_config["priority"] = datapoint_priority(datapoint)

        prefix = ""
        if prefix_function:
            prefix = f'{datapoint.get("MenuItem", "")} - '
        if prefix_opline:
            prefix = f'{prefix}{datapoint.get("OpLine", "")} '
        dp_config["entity_prefix"] = prefix

        configs.append(dp_config)
    return configs


def dp_configs_for_hatype(entry: ConfigEntry, hatype: str) -> list[dict]:
    """Runtime configs for the datapoints this platform is responsible for."""
    return [
        dp_config
        for dp_config in build_dp_configs(entry)
        if (dp_config.get("DPDescr") or {}).get("HAType") == hatype
    ]
