#!/usr/bin/env python3
"""Verify that project, integration, and release-tag versions agree."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$")


def project_versions(root: Path = ROOT) -> tuple[str, str]:
    """Return the manifest and Python project versions."""
    manifest = json.loads(
        (root / "custom_components" / "wait_for_wolt" / "manifest.json").read_text()
    )
    project = tomllib.loads((root / "pyproject.toml").read_text())
    return manifest["version"], project["project"]["version"]


def check_version(tag: str | None = None, root: Path = ROOT) -> str:
    """Validate version consistency and an optional v-prefixed release tag."""
    manifest_version, project_version = project_versions(root)
    if manifest_version != project_version:
        raise ValueError(
            f"manifest version {manifest_version!r} does not match "
            f"project version {project_version!r}"
        )
    if VERSION_RE.fullmatch(manifest_version) is None:
        raise ValueError(
            "version must use MAJOR.MINOR.PATCH with an optional PEP 440 "
            "aN, bN, or rcN prerelease suffix"
        )
    if tag is not None and tag != f"v{manifest_version}":
        raise ValueError(f"release tag {tag!r} must be exactly 'v{manifest_version}'")
    return manifest_version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Optional release tag, for example v0.1.0b1")
    args = parser.parse_args()
    try:
        version = check_version(args.tag)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as err:
        print(f"version check failed: {err}", file=sys.stderr)
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
