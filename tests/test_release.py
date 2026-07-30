"""Tests for release version and package invariants."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.build_release import HACS_ARCHIVE_NAME, build
from scripts.check_version import ROOT, check_version


def test_project_versions_agree() -> None:
    """Keep the Home Assistant manifest and project metadata synchronized."""
    assert check_version() == "0.1.0b1"
    assert check_version("v0.1.0b1") == "0.1.0b1"


def test_release_tag_must_match_version() -> None:
    """Refuse to publish a tag that disagrees with shipped metadata."""
    with pytest.raises(ValueError, match="must be exactly"):
        check_version("v9.9.9")


def test_hacs_uses_the_fixed_release_asset() -> None:
    """Make HACS install the exact validated asset instead of a source archive."""
    manifest = json.loads((ROOT / "hacs.json").read_text())
    assert manifest["zip_release"] is True
    assert manifest["filename"] == HACS_ARCHIVE_NAME


def test_release_archive_is_clean_and_checksum_matches(tmp_path: Path) -> None:
    """Package component files at HACS's integration extraction root."""
    archive = build("test", tmp_path)
    checksum, filename = archive.with_suffix(".sha256").read_text().split()

    assert filename == archive.name
    assert checksum == hashlib.sha256(archive.read_bytes()).hexdigest()
    hacs_archive = tmp_path / HACS_ARCHIVE_NAME
    hacs_checksum, hacs_filename = (
        hacs_archive.with_suffix(".sha256").read_text().split()
    )
    assert hacs_filename == HACS_ARCHIVE_NAME
    assert hacs_checksum == checksum
    assert hacs_archive.read_bytes() == archive.read_bytes()
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    assert "manifest.json" in names
    assert "__init__.py" in names
    assert "brand/icon.png" in names
    assert not any(name.startswith("wait_for_wolt/") for name in names)
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
