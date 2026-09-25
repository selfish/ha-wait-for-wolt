"""Safety boundaries for the explicit HACS repair; fixtures are synthetic."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import repair_hacs_205 as repair


@pytest.fixture
def installation(tmp_path, monkeypatch):
    original = b"synthetic source\n" + repair.OLD + b"\n"
    fixed = original.replace(repair.OLD, repair.NEW)
    monkeypatch.setattr(repair, "ORIGINAL_SHA256", hashlib.sha256(original).hexdigest())
    monkeypatch.setattr(repair, "REPAIRED_SHA256", hashlib.sha256(fixed).hexdigest())
    root = tmp_path / "custom_components/hacs"
    (root / "repositories").mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({"version": "2.0.5"}))
    target = root / "repositories/base.py"
    target.write_bytes(original)
    target.chmod(0o640)
    return tmp_path, target, original, fixed


def test_preview_apply_idempotence_restore(installation):
    config, target, original, fixed = installation
    assert repair.repair(config) == "Verified; would repair"
    assert target.read_bytes() == original
    assert not (config / ".hacs-205-release-url-backup").exists()
    assert repair.repair(config, apply=True).startswith("Repaired")
    assert target.read_bytes() == fixed
    assert target.stat().st_mode & 0o777 == 0o640
    backup = config / ".hacs-205-release-url-backup/base.py"
    assert backup.read_bytes() == original
    assert backup.stat().st_mode & 0o777 == 0o600
    assert repair.repair(config, apply=True) == "Already repaired"
    assert repair.repair(config, restore=True) == "Verified; would restore"
    assert target.read_bytes() == fixed
    assert repair.repair(config, apply=True, restore=True).startswith("Restored")
    assert target.read_bytes() == original


def test_refuses_modified_source(installation):
    config, target, original, _ = installation
    target.write_bytes(original + b"local changes")
    with pytest.raises(ValueError, match="exact supported"):
        repair.repair(config, apply=True)
    assert target.read_bytes() == original + b"local changes"


def test_refuses_other_hacs_version(installation):
    config, target, original, _ = installation
    (target.parent.parent / "manifest.json").write_text('{"version":"2.0.6"}')
    with pytest.raises(ValueError, match="only to HACS"):
        repair.repair(config, apply=True)
    assert target.read_bytes() == original


def test_refuses_corrupt_backup(installation):
    config, target, _, fixed = installation
    repair.repair(config, apply=True)
    (config / ".hacs-205-release-url-backup/base.py").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Backup checksum"):
        repair.repair(config, apply=True, restore=True)
    assert target.read_bytes() == fixed


def test_refuses_overwriting_existing_backup(installation):
    config, target, original, _ = installation
    backup = config / ".hacs-205-release-url-backup/base.py"
    backup.parent.mkdir()
    backup.write_bytes(b"another backup")
    with pytest.raises(ValueError, match="Existing backup"):
        repair.repair(config, apply=True)
    assert target.read_bytes() == original


@pytest.mark.parametrize(
    "ref,expected",
    [
        ("tags/v0.1.0b3", "v0.1.0b3"),
        ("v0.1.0b3", "v0.1.0b3"),
        ("tags/tags/v1", "tags/v1"),
    ],
)
def test_strips_only_the_internal_prefix(ref, expected):
    namespace = {
        "self": SimpleNamespace(
            ref=ref, repository_manifest=SimpleNamespace(filename="wait_for_wolt.zip")
        )
    }
    arguments = eval(b"dict(" + repair.NEW + b")", namespace)
    assert arguments == {"version": expected, "filename": "wait_for_wolt.zip"}
