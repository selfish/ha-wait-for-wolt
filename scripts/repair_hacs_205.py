#!/usr/bin/env python3
"""Explicit, reversible repair for the unmodified HACS 2.0.5 ZIP URL bug.

Not imported or run by Wait for Wolt. Requires an administrator invocation.
Upstream: hacs/integration@c0dfd8b44297c3673c21973e2539375a53687a9c.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

# Public source-file integrity digests, not credentials.
ORIGINAL_SHA256 = "17aeee13aa48153f17c0de654ce6d4cd03495f21be3c57a218bf1909fefc4d2e"  # pragma: allowlist secret
REPAIRED_SHA256 = "0544f6fc545827ec2fcea00d97b328c120668fb09da84b23a3fbb31d7fe39e88"  # pragma: allowlist secret
OLD = b"version=self.ref,\n                        filename=self.repository_manifest.filename,"
NEW = b'version=self.ref.removeprefix("tags/"),\n                        filename=self.repository_manifest.filename,'


def repaired_source(source: bytes) -> bytes:
    """Refuse other versions, local modifications and ambiguous patch locations."""
    digest = hashlib.sha256(source).hexdigest()
    if digest == REPAIRED_SHA256:
        return source
    if digest != ORIGINAL_SHA256 or source.count(OLD) != 1:
        raise ValueError("Not the exact supported upstream HACS 2.0.5 file")
    result = source.replace(OLD, NEW, 1)
    if hashlib.sha256(result).hexdigest() != REPAIRED_SHA256:
        raise ValueError("Unexpected repaired checksum")
    return result


def repair(config: Path, *, apply: bool = False, restore: bool = False) -> str:
    """Preview by default; preserve a private original before atomic replacement."""
    root = config / "custom_components" / "hacs"
    if json.loads((root / "manifest.json").read_text())["version"] != "2.0.5":
        raise ValueError("This repair applies only to HACS 2.0.5")
    target = root / "repositories" / "base.py"
    source = target.read_bytes()
    backup = config / ".hacs-205-release-url-backup" / "base.py"
    if restore:
        if hashlib.sha256(source).hexdigest() != REPAIRED_SHA256:
            raise ValueError("Refusing to restore over an unexpected file")
        result = backup.read_bytes()
        if hashlib.sha256(result).hexdigest() != ORIGINAL_SHA256:
            raise ValueError("Backup checksum mismatch")
    else:
        result = repaired_source(source)
    if source == result:
        return "Already repaired"
    if not apply:
        return "Verified; would " + ("restore" if restore else "repair")
    if not restore:
        backup.parent.mkdir(mode=0o700, exist_ok=True)
        if backup.exists():
            if backup.read_bytes() != source:
                raise ValueError("Existing backup differs; refusing overwrite")
        else:
            with backup.open("xb") as handle:
                handle.write(source)
            backup.chmod(0o600)
    stat = target.stat()
    fd, temporary = tempfile.mkstemp(prefix=".base-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(result)
            handle.flush()
            os.fsync(handle.fileno())
        shutil.copystat(target, temporary)
        os.chown(temporary, stat.st_uid, stat.st_gid)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    assert target.read_bytes() == result
    return (
        "Restored" if restore else "Repaired"
    ) + "; restart Home Assistant to load it"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/config"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    print(repair(args.config, apply=args.apply, restore=args.restore))


if __name__ == "__main__":
    main()
