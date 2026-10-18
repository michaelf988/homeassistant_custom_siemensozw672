"""Keep the configured datapoints pointed at the right OZW672 datapoint Ids.

The OZW672 numbers its datapoints when it generates its menu tree, and it
regenerates that tree on its own - after a restart, a power cut, a firmware or
system-definition update, or when the bus is re-scanned. The Ids then shift, but
the config entry still holds the Ids from discovery. Before this module existed
nothing noticed: every datapoint kept being polled under its old Id, so most
entities silently showed a *neighbouring* datapoint's value (a fan speed as the
return temperature, a date as the clock), and a write went to the wrong
datapoint on the controller.

What identifies a datapoint across a regeneration is not its Id but where it
sits: the menu path recorded at discovery (MenuItem, e.g. "Heizkreis 1" or
"Diagnose->Kessel"), its operating line / text id (OpLine), and - recorded from
the first verification on - its bus address (Address + DpSubKey). This module

* detects a regeneration: the device list reports when each device's tree was
  generated (TreeDate/TreeTime). That stamp is stored, and comparing it costs one
  request. As a second net that does not depend on the stamp, every poll checks
  the description name of one datapoint of its tier, rotating through them;
* walks only the menus the configured datapoints live in and matches each
  datapoint again;
* rewrites the stored Ids, and marks datapoints it cannot match unambiguously as
  unresolved. Those are no longer polled or written - an unavailable entity is
  better than one showing, or writing, something else - and a repair issue lists
  them.

Entities keep their unique_id (it is built from the OpLine, not the Id), so
entity ids, dashboards, automations and history survive a remap untouched.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .api import SiemensOzw672ApiClient, SiemensOzw672ApiError, SiemensOzw672CredentialsError
from .const import (
    CONF_DATAPOINTS,
    CONF_DEVICE_ID,
    CONF_DEVICE_LONGNAME,
    CONF_TREESTAMP,
    DOMAIN,
    DP_ADDRESS,
    DP_SUBKEY,
    DP_UNRESOLVED,
    ISSUE_UNRESOLVED,
    MENU_SEPARATOR,
)

_LOGGER: logging.Logger = logging.getLogger(__package__)


class VerificationPending(Exception):
    """Polling must wait: the datapoint Ids are not (yet) known to be right."""


def _norm(text) -> str:
    """Compare device texts loosely: padding and case are not meaningful."""
    return " ".join(str(text or "").split()).casefold()


def tree_stamp(devices, device_id: str | None, longname: str | None) -> str | None:
    """When the configured device's menu tree was generated, per the device list.

    The device is matched by serial number first (CONF_DEVICE_ID is
    "<OZW serial>:<device serial>"), then by "Addr Type", which is what the menu
    tree shows as the device's name.
    """
    serial = str(device_id or "").split(":", 1)[-1] if device_id else None
    match = None
    for device in devices or []:
        if serial and str(device.get("SerialNr")) == serial:
            match = device
            break
    if match is None and longname:
        for device in devices or []:
            if _norm(f'{device.get("Addr")} {device.get("Type")}') == _norm(longname):
                match = device
                break
    if match is None:
        return None
    date, clock = match.get("TreeDate"), match.get("TreeTime")
    if not date and not clock:
        return None
    return f"{date or ''} {clock or ''}".strip()


@dataclass
class Resolution:
    """What matching the configured datapoints against the device produced."""

    datapoints: list[dict]
    moved: list[tuple[str, str, str]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def _display(datapoint: dict) -> str:
    return f'{datapoint.get("MenuItem", "")} / {datapoint.get("OpLine", "")} {datapoint.get("Name", "")}'.strip()


def _candidates(datapoint: dict, items: list[dict]) -> list[dict]:
    """The menu entries that are this datapoint, most specific evidence first."""
    address = datapoint.get(DP_ADDRESS)
    if address:
        subkey = str(datapoint.get(DP_SUBKEY, "0"))
        by_address = [
            item for item in items
            if str(item.get("Address")) == str(address)
            and str(item.get("DpSubKey", "0")) == subkey
        ]
        if by_address:
            return by_address
    opline = str(datapoint.get("OpLine", ""))
    by_opline = [
        item for item in items if str((item.get("Text") or {}).get("Id", "")) == opline
    ]
    if len(by_opline) > 1:
        names = {
            _norm(datapoint.get("Name")),
            _norm((datapoint.get("DPDescr") or {}).get("Name")),
        } - {""}
        by_name = [
            item for item in by_opline
            if _norm((item.get("Text") or {}).get("Long")) in names
        ]
        if by_name:
            return by_name
    return by_opline


def resolve_datapoints(datapoints: list[dict], menus: dict[str, list[dict] | None]) -> Resolution:
    """Match every configured datapoint against the freshly read menus.

    `menus` maps a menu path to that menu's datapoint items, or to None when the
    path no longer exists. Pure function - no device access - so it can be tested
    on its own.
    """
    result: list[dict] = []
    moved: list[tuple[str, str, str]] = []
    unresolved: list[str] = []
    claimed: dict[str, int] = {}

    for datapoint in datapoints:
        items = menus.get(datapoint.get("MenuItem", ""))
        matches = _candidates(datapoint, items) if items else []
        updated = dict(datapoint)
        if len(matches) != 1:
            updated[DP_UNRESOLVED] = True
            unresolved.append(_display(datapoint))
            result.append(updated)
            continue
        item = matches[0]
        new_id = str(item.get("Id"))
        if new_id != str(datapoint.get("Id")):
            moved.append((_display(datapoint), str(datapoint.get("Id")), new_id))
        updated["Id"] = new_id
        if item.get("WriteAccess") is not None:
            updated["WriteAccess"] = item["WriteAccess"]
        if item.get("Address") is not None:
            updated[DP_ADDRESS] = str(item["Address"])
            updated[DP_SUBKEY] = str(item.get("DpSubKey", "0"))
        updated.pop(DP_UNRESOLVED, None)
        if new_id in claimed:
            # Two configured datapoints landing on one device datapoint means the
            # evidence is wrong for at least one of them; trust neither.
            other = result[claimed[new_id]]
            if not other.get(DP_UNRESOLVED):
                other[DP_UNRESOLVED] = True
                unresolved.append(_display(other))
            updated[DP_UNRESOLVED] = True
            unresolved.append(_display(datapoint))
        else:
            claimed[new_id] = len(result)
        result.append(updated)

    moved = [entry for entry in moved if entry[0] not in unresolved]
    return Resolution(datapoints=result, moved=moved, unresolved=unresolved)


async def async_read_menus(
    client: SiemensOzw672ApiClient, longname: str | None, paths: set[str]
) -> dict[str, list[dict] | None]:
    """Read the datapoint items of each menu path, walking only what is needed.

    Menu listings are cached by Id, so a menu shared by several paths is read
    once. A path segment that matches no menu, or more than one, maps the whole
    path to None. Raises SiemensOzw672ApiError when the device does not answer.
    """
    listing_cache: dict[str, dict] = {}

    async def listing(menu_id: str) -> dict:
        if menu_id not in listing_cache:
            response = await client.async_get_menutree(menu_id)
            if response is None:
                raise SiemensOzw672ApiError(f"Could not list menu {menu_id or '(root)'}")
            listing_cache[menu_id] = response
        return listing_cache[menu_id]

    roots = (await listing("")).get("MenuItems") or []
    root = [m for m in roots if _norm((m.get("Text") or {}).get("Long")) == _norm(longname)]
    if len(root) != 1:
        _LOGGER.warning(
            "Could not find the device %r in the OZW672 menu tree (found: %s)",
            longname, ", ".join(str((m.get("Text") or {}).get("Long")) for m in roots),
        )
        return {path: None for path in paths}
    root_id = str(root[0]["Id"])

    menus: dict[str, list[dict] | None] = {}
    for path in sorted(paths):
        menu_id: str | None = root_id
        for segment in [s for s in path.split(MENU_SEPARATOR)] if path else []:
            children = (await listing(menu_id)).get("MenuItems") or []
            found = [
                m for m in children
                if _norm((m.get("Text") or {}).get("Long")) == _norm(segment)
            ]
            if len(found) != 1:
                menu_id = None
                break
            menu_id = str(found[0]["Id"])
        menus[path] = None if menu_id is None else (
            (await listing(menu_id)).get("DatapointItems") or []
        )
    return menus


class DatapointVerifier:
    """Decides whether the stored Ids can be trusted, and repairs them if not.

    One per loaded config entry, shared by all polling tiers. Every tier calls
    async_before_poll() first; the lock makes sure only one of them talks to the
    device about it, and the others wait for its verdict.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: SiemensOzw672ApiClient
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self._lock = asyncio.Lock()
        self._verified = False
        self._force_walk = False
        self._update_pending = False
        self._rotation: dict[str, int] = {}
        self._accepted: set[tuple[str, str]] = set()
        self._session_generation = client.session_generation

    # --- signals from the coordinators -------------------------------------------

    def connection_lost(self) -> None:
        """A whole poll failed. The device may have restarted - check the stamp again."""
        self._verified = False

    # --- gate in front of every poll ---------------------------------------------

    async def async_before_poll(self, priority: str, datapoints: list[dict]) -> None:
        """Raise VerificationPending unless polling these datapoints is safe."""
        async with self._lock:
            if self._update_pending:
                raise VerificationPending("the datapoints are being re-mapped")
            if self.client.session_generation != self._session_generation:
                # The device threw our session away since the last check, most
                # likely because it restarted. Check the tree stamp again.
                self._session_generation = self.client.session_generation
                self._verified = False
            if not self._verified:
                await self._async_verify()
            if self._update_pending:
                raise VerificationPending("the datapoints are being re-mapped")
            mismatch = await self._async_spot_check(priority, datapoints)
            if mismatch is None:
                return
            self._verified = False
            self._force_walk = True
            await self._async_verify()
            if not self._update_pending:
                # The walk found this datapoint where it always was, so only its
                # text differs from discovery (a system-definition update can do
                # that). Believe the menu tree and stop flagging it.
                self._accepted.add(mismatch)
            raise VerificationPending(
                "a datapoint no longer matched its description; re-checked the menu tree"
            )

    # --- the actual work ----------------------------------------------------------

    async def _async_verify(self) -> None:
        """Check the tree stamp and re-map if needed. Leaves _verified set on success."""
        data = self.entry.data
        datapoints = list(data.get(CONF_DATAPOINTS) or [])
        devices = await self.client.async_get_devices()
        if devices is None:
            raise VerificationPending("the OZW672 device list could not be read")
        stamp = tree_stamp(devices, data.get(CONF_DEVICE_ID), data.get(CONF_DEVICE_LONGNAME))
        stored = data.get(CONF_TREESTAMP)
        needs_walk = (
            self._force_walk
            or stamp is None
            or stamp != stored
            or any(dp.get(DP_UNRESOLVED) for dp in datapoints)
        )
        if not needs_walk:
            self._verified = True
            return

        _LOGGER.info(
            "Verifying %d OZW672 datapoint(s) against the device's menu tree "
            "(tree generated: %s, last verified against: %s)",
            len(datapoints), stamp or "unknown", stored or "never",
        )
        try:
            menus = await async_read_menus(
                self.client,
                data.get(CONF_DEVICE_LONGNAME),
                {dp.get("MenuItem", "") for dp in datapoints},
            )
        except SiemensOzw672CredentialsError:
            # Not a reason to wait: the coordinator turns it into a reauth prompt.
            raise
        except SiemensOzw672ApiError as exception:
            raise VerificationPending(f"menu tree could not be read: {exception}") from exception

        resolution = resolve_datapoints(datapoints, menus)
        self._force_walk = False
        self._report(resolution)

        new_data = {**data, CONF_DATAPOINTS: resolution.datapoints}
        if stamp is not None:
            new_data[CONF_TREESTAMP] = stamp
        if new_data == dict(data):
            self._verified = True
            return
        # The entry listener reloads the entry, which rebuilds the coordinators
        # and entities from the corrected Ids. Until then nothing is polled.
        self._update_pending = True
        self.hass.config_entries.async_update_entry(self.entry, data=new_data)

    def _report(self, resolution: Resolution) -> None:
        for display, old, new in resolution.moved:
            _LOGGER.info("OZW672 datapoint %s moved from Id %s to %s", display, old, new)
        if resolution.moved:
            _LOGGER.warning(
                "The OZW672 renumbered its datapoints; %d of them were re-mapped. "
                "Entities keep their ids and history.", len(resolution.moved),
            )
        issue_id = f"{ISSUE_UNRESOLVED}_{self.entry.entry_id}"
        if resolution.unresolved:
            _LOGGER.error(
                "%d OZW672 datapoint(s) could not be found again and are no longer "
                "polled: %s", len(resolution.unresolved), "; ".join(resolution.unresolved),
            )
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_UNRESOLVED,
                translation_placeholders={
                    "count": str(len(resolution.unresolved)),
                    "datapoints": "\n".join(f"- {d}" for d in resolution.unresolved),
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    async def _async_spot_check(
        self, priority: str, datapoints: list[dict]
    ) -> tuple[str, str] | None:
        """Confirm one datapoint of this tier still is what it was at discovery.

        One description request per poll, rotating through the tier, compared on
        the name the same endpoint returned at discovery. Returns (Id, name now
        reported) on a definite mismatch, otherwise None; a datapoint that cannot
        be described right now is not evidence either way.
        """
        checkable = [dp for dp in datapoints if (dp.get("DPDescr") or {}).get("Name")]
        if not checkable:
            return None
        index = self._rotation.get(priority, 0) % len(checkable)
        self._rotation[priority] = index + 1
        datapoint = checkable[index]
        try:
            descr = await self.client.async_get_description(datapoint["Id"])
        except SiemensOzw672ApiError as exception:
            _LOGGER.debug("Spot check of %s skipped: %s", datapoint.get("Id"), exception)
            return None
        if descr is None or not descr.get("Name"):
            return None
        expected = datapoint["DPDescr"]["Name"]
        actual = (str(datapoint.get("Id")), _norm(descr["Name"]))
        if actual[1] == _norm(expected) or actual in self._accepted:
            return None
        _LOGGER.warning(
            "OZW672 datapoint Id %s should be %r but the device now describes it as "
            "%r - the menu tree was regenerated; re-mapping all datapoints",
            datapoint.get("Id"), expected, descr["Name"],
        )
        return actual
