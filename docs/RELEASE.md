# Release process

Wait for Wolt uses `MAJOR.MINOR.PATCH` versions. Alpha, beta, and release-candidate builds use the PEP 440 suffixes `aN`, `bN`, and `rcN`, which Home Assistant and HACS parse through AwesomeVersion. Examples: `0.1.0b1`, `0.1.0rc1`, and `0.1.0`.

The same version must appear in:

- `custom_components/wait_for_wolt/manifest.json`;
- `pyproject.toml`;
- the changelog section;
- the Git tag, prefixed by `v`.

`scripts/check_version.py` enforces metadata and tag agreement. `scripts/build_release.py` creates a deterministic versioned archive/checksum plus byte-identical `wait_for_wolt.zip` and `wait_for_wolt.sha256` assets. The stable filename is declared in `hacs.json`, so HACS installs the validated release asset rather than GitHub's automatically generated source archive. CI also packages the exact reviewed commit.

## Release checklist

1. Move release notes out of **Unreleased** in `CHANGELOG.md`.
2. Run the complete local suite:

   ```bash
   uv sync --frozen
   uv run ruff check .
   uv run ruff format --check .
   uv run pytest
   uv run python scripts/check_version.py
   scripts/canary.sh
   ```

3. Verify Hassfest, HACS validation with no ignored checks, secret scanning, and exact-commit packaging on the pull request.
4. Review the downloaded CI archive and checksum, then execute the operational matrix in [CANARY.md](CANARY.md).
5. Merge to `main`; do not release from a side branch.
6. Create and push an annotated `v<version>` tag at the exact `main` head.
7. The release workflow re-runs all gates, verifies the tag points at current `main`, creates the archive/checksum/metadata set, and creates a full GitHub release. Prerelease versions are marked as prereleases automatically.
8. Verify a fresh HACS custom-repository install and upgrade using the full GitHub release.

Never create a GitHub release manually after a failed workflow. Correct the cause, update the version if an immutable tag was already published, and rerun from a new tag.

## HACS default

Default-store submission happens only after:

- at least one stable full GitHub release;
- fresh-install and preceding-version upgrade tests;
- the release canary and rollback matrix;
- HACS Action success with no ignores;
- complete public documentation and approved brand asset.

The integration is not country-limited, so `hacs.json` deliberately has no `country` key.
