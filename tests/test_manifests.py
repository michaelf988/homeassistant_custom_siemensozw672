"""Checks that mirror what hassfest and the HACS action enforce.

These all failed on the first CI run. Reproducing the rules here means the next
one is caught in a two-second local test run instead of a five-minute round trip
through GitHub Actions.
"""
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "siemens_ozw672"
TRANSLATIONS = COMPONENT / "translations"
HACS_JSON = ROOT / "hacs.json"

# hacs.json accepts a fixed set of keys and rejects anything else outright.
# https://hacs.xyz/docs/publish/include#check-hacs-manifest
ALLOWED_HACS_KEYS = {
    "name", "content_in_root", "filename", "country", "homeassistant",
    "persistent_directory", "hacs", "hide_default_branch", "render_readme",
    "zip_release",
}

URL = re.compile(r"https?://")


def _strings(value, path=""):
    """Every string in a nested JSON structure, with its dotted path."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]")


@pytest.mark.parametrize(
    "translation_file", sorted(TRANSLATIONS.glob("*.json")), ids=lambda p: p.name
)
def test_translations_contain_no_urls(translation_file):
    """hassfest rejects URLs in translation strings.

    "the string should not contain URLs, please use description placeholders
    instead" - it failed on the setup step, which linked to the repository.
    """
    offenders = [
        (path, text)
        for path, text in _strings(json.loads(translation_file.read_text()))
        if URL.search(text)
    ]
    assert not offenders, f"URLs in {translation_file.name}: {offenders}"


def test_hacs_json_has_no_unknown_keys():
    """The HACS action fails on extra keys.

    'domains' and 'iot_class' were carried over from an older schema and are not
    accepted any more: "extra keys not allowed @ data['domains']".
    """
    unknown = set(json.loads(HACS_JSON.read_text())) - ALLOWED_HACS_KEYS
    assert not unknown, f"hacs.json carries keys HACS rejects: {sorted(unknown)}"


REPO = "michaelf988/homeassistant_custom_siemensozw672"


def test_manifest_points_at_this_fork():
    """Documentation and the issue tracker must reach the maintainers of this fork.

    Both still pointed at the upstream repository, so Home Assistant's "visit
    documentation" link and every reported issue went to the original author.
    """
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert manifest["documentation"] == f"https://github.com/{REPO}"
    assert manifest["issue_tracker"] == f"https://github.com/{REPO}/issues"
    assert manifest["codeowners"] == ["@michaelf988"]


def test_the_startup_banner_points_at_this_fork():
    """ISSUE_URL is what the log tells users to open an issue on."""
    from custom_components.siemens_ozw672.const import ISSUE_URL

    assert ISSUE_URL == f"https://github.com/{REPO}/issues"


@pytest.mark.parametrize("doc", ["README.md", "info.md"], ids=lambda p: p)
def test_docs_carry_no_badges(doc):
    """The badge row was stale and mostly decorative.

    It advertised release 0.3.9 long after 0.5.0, claimed pre-commit and Black were
    in use when neither is configured here, and every link pointed upstream.
    """
    text = (ROOT / doc).read_text()
    assert "img.shields.io" not in text
    assert "-shield]" not in text


@pytest.mark.parametrize("doc", ["README.md", "info.md", "CONTRIBUTING.md"], ids=lambda p: p)
def test_docs_have_no_unresolved_reference_links(doc):
    """A link definition removed with the badges must not leave a dangling reference."""
    text = (ROOT / doc).read_text()
    defined = set(re.findall(r"^\[([^\]]+)\]:", text, re.M))
    used = set(re.findall(r"\]\[([^\]]+)\]", text))
    assert used <= defined, f"{doc} references undefined links: {sorted(used - defined)}"


def test_the_release_archive_name_matches_the_workflow():
    """hacs.json names the asset the release workflow has to produce."""
    filename = json.loads(HACS_JSON.read_text())["filename"]
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert filename in workflow


def test_the_test_requirements_are_what_ci_installs():
    """CI installs requirements_test.txt, so the pip cache must point at it."""
    workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text()
    assert "cache-dependency-path: requirements_test.txt" in workflow
    assert "pip install -r requirements_test.txt" in workflow


def test_every_config_step_is_translated():
    """A step without strings shows the user raw keys."""
    from custom_components.siemens_ozw672.config_flow import (
        SiemensOzw672FlowHandler,
        SiemensOzw672OptionsFlowHandler,
    )

    strings = json.loads((TRANSLATIONS / "en.json").read_text())
    for handler, section in (
        (SiemensOzw672FlowHandler, "config"),
        (SiemensOzw672OptionsFlowHandler, "options"),
    ):
        # vars(), not dir(): the base classes contribute the discovery steps
        # (bluetooth, dhcp, zeroconf, ...) that this integration never uses and
        # Home Assistant translates itself.
        steps = {
            name.removeprefix("async_step_")
            for name in vars(handler)
            if name.startswith("async_step_")
        }
        translated = set(strings[section]["step"])
        assert steps <= translated, (
            f"{section} steps without translations: {sorted(steps - translated)}"
        )
