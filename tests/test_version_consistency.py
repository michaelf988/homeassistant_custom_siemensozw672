"""The version is declared in more than one place, so it has to be checked.

Release tags are verified against manifest.json, and const.VERSION is what the
startup banner and device_info report. A drift between them is only noticed at
release time otherwise - the same way the config flow's hard-coded MINOR_VERSION
drifted away from const and made every new entry look out of date.
"""
import json
import pathlib

from custom_components.siemens_ozw672.const import (
    CONF_MINOR_VERSION,
    CONF_VERSION,
    VERSION,
)
from custom_components.siemens_ozw672.config_flow import SiemensOzw672FlowHandler

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "custom_components" / "siemens_ozw672" / "manifest.json"
CHANGELOG = ROOT / "CHANGELOG.md"


def test_manifest_and_const_agree():
    """manifest.json is what HACS reads; const.VERSION is what the user sees."""
    assert json.loads(MANIFEST.read_text())["version"] == VERSION


def test_the_changelog_documents_the_current_version():
    """A release without a changelog entry is a release nobody can read."""
    assert f"## {VERSION}" in CHANGELOG.read_text()


def test_the_config_flow_creates_entries_at_the_current_schema_version():
    """A flow that lags const makes every new entry look like it needs migrating."""
    assert SiemensOzw672FlowHandler.VERSION == CONF_VERSION
    assert SiemensOzw672FlowHandler.MINOR_VERSION == CONF_MINOR_VERSION


def test_release_notes_come_out_of_the_changelog():
    """The release workflow uses this as the release body, so it must not be empty."""
    import subprocess
    import sys

    notes = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "set_version.py"), "--notes"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    assert notes, "no changelog section for the current version"
    # The heading itself is not part of the body, and the next version's section
    # must not bleed into it.
    assert not notes.startswith("## ")
    assert "\n## " not in notes


def test_manifest_declares_what_home_assistant_expects():
    """hassfest checks these; a missing iot_class is a warning on every start."""
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["domain"] == "siemens_ozw672"
    assert manifest["iot_class"] == "local_polling"
    assert manifest["integration_type"] == "hub"
    assert manifest["config_flow"] is True
