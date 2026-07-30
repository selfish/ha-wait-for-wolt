#!/usr/bin/env python3
"""Build a deterministic, inspectable HACS integration archive."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import time
import zipfile
from pathlib import Path

try:
    from .check_version import ROOT, check_version
except ImportError:  # Direct execution: python scripts/build_release.py
    from check_version import ROOT, check_version

COMPONENT = ROOT / "custom_components" / "wait_for_wolt"
ALLOWED_CACHE_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache"}


def archive_files() -> list[Path]:
    """Return only shipped component files in stable order."""
    files = [
        path
        for path in COMPONENT.rglob("*")
        if path.is_file() and not ALLOWED_CACHE_PARTS.intersection(path.parts)
    ]
    if not files:
        raise ValueError("integration contains no files")
    return sorted(files, key=lambda path: path.relative_to(COMPONENT).as_posix())


def build(label: str | None = None, output_dir: Path | None = None) -> Path:
    """Build the release archive and adjacent SHA-256 checksum."""
    version = check_version()
    label = label or version
    output_dir = output_dir or ROOT / "dist"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"wait_for_wolt-{label}.zip"

    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "315532800"))
    date_parts = time.gmtime(max(epoch, 315532800))
    timestamp = (
        date_parts.tm_year,
        date_parts.tm_mon,
        date_parts.tm_mday,
        date_parts.tm_hour,
        date_parts.tm_min,
        date_parts.tm_sec,
    )

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for source in archive_files():
            relative = source.relative_to(COMPONENT)
            target = Path("wait_for_wolt") / relative
            info = zipfile.ZipInfo(target.as_posix(), timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            bundle.writestr(info, source.read_bytes())

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".sha256").write_text(f"{digest}  {archive.name}\n")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", help="Archive label; defaults to project version")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    archive = build(args.label, args.output_dir)
    print(archive)


if __name__ == "__main__":
    main()
