#!/usr/bin/env python3
"""Set the integration version in every place that carries it.

The version lives in two files that have to agree: manifest.json (what Home
Assistant and HACS read) and const.py (what the startup banner and device_info
report). Release tags are checked against manifest.json, so bump with

    python scripts/set_version.py 0.6.0

commit the result, and tag that commit.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "custom_components" / "siemens_ozw672" / "manifest.json"
CONST = ROOT / "custom_components" / "siemens_ozw672" / "const.py"
CHANGELOG = ROOT / "CHANGELOG.md"

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def read_version() -> str:
    """The version currently declared in the manifest."""
    return json.loads(MANIFEST.read_text())["version"]


def write_version(version: str) -> None:
    """Write the version into the manifest and const.py."""
    manifest = json.loads(MANIFEST.read_text())
    manifest["version"] = version
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")

    const = CONST.read_text()
    updated, count = re.subn(
        r'^VERSION = "[^"]*"$', f'VERSION = "{version}"', const, count=1, flags=re.M
    )
    if count != 1:
        raise SystemExit(f"Could not find a VERSION assignment in {CONST}")
    CONST.write_text(updated)


def changelog_has(version: str) -> bool:
    """Whether the changelog already documents this version."""
    if not CHANGELOG.exists():
        return True
    return f"## {version}" in CHANGELOG.read_text()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?", help="new version, e.g. 0.6.0")
    parser.add_argument(
        "--check", action="store_true",
        help="print the current version instead of setting one",
    )
    args = parser.parse_args()

    if args.check or not args.version:
        print(read_version())
        return 0

    version = args.version.removeprefix("v")
    if not SEMVER.match(version):
        raise SystemExit(f"{version!r} is not a MAJOR.MINOR.PATCH version")

    write_version(version)
    print(f"Version set to {version}")
    if not changelog_has(version):
        print(
            f"Note: CHANGELOG.md has no '## {version}' section yet.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
