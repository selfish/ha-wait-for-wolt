"""Tests for release version and package invariants."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from scripts.build_release import build
from scripts.check_version import check_version


def test_project_versions_agree() -> None:
    """Keep the Home Assistant manifest and project metadata synchronized."""
    assert check_version() == "0.1.0b1"
    assert check_version("v0.1.0b1") == "0.1.0b1"


def test_release_tag_must_match_version() -> None:
    """Refuse to publish a tag that disagrees with shipped metadata."""
    with pytest.raises(ValueError, match="must be exactly"):
        check_version("v9.9.9")


def test_release_archive_is_clean_and_checksum_matches(tmp_path: Path) -> None:
    """Package only the integration under the HACS-compatible directory root."""
    archive = build("test", tmp_path)
    checksum, filename = archive.with_suffix(".sha256").read_text().split()

    assert filename == archive.name
    assert checksum == hashlib.sha256(archive.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    assert "wait_for_wolt/manifest.json" in names
    assert all(name.startswith("wait_for_wolt/") for name in names)
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
