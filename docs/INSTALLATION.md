# Installation troubleshooting

## HACS release-asset URL failure

The b2 rollout on 2026-09-25 exposed a HACS 2.0.5 download-path defect. HACS
prefixed the selected release with `tags/` and used that ref in its asset URL:

- Incorrect: `https://github.com/selfish/ha-wait-for-wolt/releases/download/tags/v0.1.0b2/wait_for_wolt.zip` — HTTP 404.
- Correct: `https://github.com/selfish/ha-wait-for-wolt/releases/download/v0.1.0b2/wait_for_wolt.zip` — HTTP 200.

The source of the extra prefix is HACS's `async_install` / `download_zip_files`
path, not the published tag or asset name. See the pinned HACS 2.0.5
[repository implementation](https://github.com/hacs/integration/blob/c0dfd8b44297c3673c21973e2539375a53687a9c/custom_components/hacs/repositories/base.py)
and [URL helper](https://github.com/hacs/integration/blob/c0dfd8b44297c3673c21973e2539375a53687a9c/custom_components/hacs/utils/url.py).
A successful HACS Action validates repository structure; it does **not** exercise
this runtime download path. A container canary validates the downloaded component,
not HACS's installer.

Inspect the actual failed URL in **Settings → System → Logs**. An HTTP 404 with
`/download/tags/` is this URL problem. A DNS timeout is a separate networking
problem; removing `tags/` does not repair DNS. Do not rotate Wolt credentials or
remove the integration to fix either download failure.

## Repair the HACS 2.0.5 installer

An administrator can apply the narrowly scoped repair in
[`scripts/repair_hacs_205.py`](../scripts/repair_hacs_205.py). It strips exactly
the internal `tags/` prefix at the release-asset call site, not in Git reference
handling. It only accepts the exact upstream HACS 2.0.5 source checksum; unknown
versions and local changes are rejected. **Wait for Wolt never runs this repair
automatically.** This is a local HACS hotfix, not an upstream HACS release.

Run it on the HA host, after creating a backup, with suitable filesystem access:

```bash
python3 repair_hacs_205.py --config /config          # verify/dry run
python3 repair_hacs_205.py --config /config --apply  # explicit modification
```

The original file is preserved under `/config/.hacs-205-release-url-backup/`.
Restart HA to load the repaired Python module. Then select the new **v0.1.0b3**
release in HACS and install normally (or use HA's `update.install` with
`version: v0.1.0b3`). HACS downloads the published `wait_for_wolt.zip` and records
the installed version through its own successful-install path. Compare installed
files against that ZIP, restart HA, and confirm the loaded component version and
HACS installed version both report b3. Do not edit HACS's private version ledger.

To undo only the hotfix, run the script with `--apply --restore` and restart HA.
It refuses to overwrite any unexpected source or use a mismatched backup. A
future HACS update may replace this repair; check its release-ZIP download behavior
before assuming the fix persists. Never apply it blindly to another HACS version.

## Manual installation or upgrade

Use a release ZIP, never a working checkout or GitHub's **Source code (zip)**.
The fixed-name `wait_for_wolt.zip` contains component files at its root. The
current beta is **v0.1.0b3**; there is no stable release yet. This path does not
require modifying HACS. Home Assistant 2026.7.0 or newer is required.

1. Make a Home Assistant backup. If upgrading, preserve the currently installed
   component outside its active `custom_components` directory. Keep the config
   entry, entity registry and device registry intact. Treat backups as secrets.
2. Download the ZIP and checksum from the **same**
   [release](https://github.com/selfish/ha-wait-for-wolt/releases/tag/v0.1.0b3).
   For b3, run these commands in a new local directory (no GitHub login needed):

   ```bash
   curl --fail --location --remote-name \
     https://github.com/selfish/ha-wait-for-wolt/releases/download/v0.1.0b3/wait_for_wolt.zip
   curl --fail --location --remote-name \
     https://github.com/selfish/ha-wait-for-wolt/releases/download/v0.1.0b3/wait_for_wolt.sha256
   sha256sum --check wait_for_wolt.sha256
   ```

   Stop on any checksum mismatch. The checksum verifies artifact consistency;
   it is not an independent publisher signature.
3. Extract into a staging directory. Confirm `manifest.json` names the
   `wait_for_wolt` domain and expected version (`0.1.0b3` for this release).
   Do not introduce another nested `wait_for_wolt` directory.
4. Create `/config/custom_components/wait_for_wolt` for a first installation,
   or replace only that directory for an upgrade, using the filesystem access
   supported by your HA installation. Put the staged component files there,
   with `manifest.json` directly inside `wait_for_wolt`.
   Compare every installed file against the ZIP and check for leftover files
   from previous versions. Do not edit `.storage` or HACS's version ledger.
   If an SSH add-on lacks SFTP and `scp` reports that subsystem failure,
   OpenSSH's `scp -O` uses legacy SCP over the same SSH connection; retain host-key
   checking. This is a transport fallback, not a reason to bypass approvals.
5. Run Home Assistant's configuration check, then restart. A restart can close
   the API connection before returning a response: check readiness and new
   startup logs rather than repeatedly issuing restarts.
6. **First installation:** open **Settings → Devices & services → Add
   integration → Wait for Wolt**. Seeing the setup form confirms that HA can
   discover the installed component; it does not verify Wolt authentication.
   No config entry or order entities exist yet. To finish setup, follow
   [Authentication](../README.md#authentication): enter a refresh token;
   access token and session ID are optional. Venue IDs are optional, one per
   line. Credentials are checked before the config entry is saved. You can
   cancel the form if you are only checking installation without credentials.
7. **After setup, or when upgrading an existing entry:** verify the Wait for Wolt
   config entry is loaded and new startup logs contain no integration errors.
   Check venue polling only if venues were configured. With no active order,
   absent order entities are normal. See the [canary matrix](CANARY.md) for
   remaining real-order and rollback gates. An upgrade should reuse the existing
   entry; do not add another account merely to check the installed files.

Manual installation does not update HACS's own `installed_version`. Its update
entity may still show an older version, or no installed version on a fresh system,
even when the component files are b3. Confirm the manifest version and installed-file
hashes, and the startup version once configured; do not mistake the HACS
ledger for runtime evidence. Reconcile via a successful supported HACS installation
when its download path is repaired, not by editing HACS's private storage.

## Current verification boundary

The b2 manual installation was verified against the published ZIP, including
configuration validation, restart, the loaded integration, idle polling and venue
polling. The later [b3 recovery record](https://github.com/selfish/ha-wait-for-wolt/issues/42)
reports a HACS-managed installation **after the explicit local HACS 2.0.5 repair**,
a 16-file exact match, persisted version ledger, restart and idle polling checks.
Neither record proves installation through an unmodified HACS downloader.

On 2026-10-09, the b3 canonical release-asset URL returned HTTP 200 and the
`/download/tags/v0.1.0b3/` form returned HTTP 404. The downloaded b3 ZIP passed its
published checksum and contained 16 component files with manifest version
`0.1.0b3`. These are download/package checks, not a fresh HACS installation or
authenticated first-run test. Unmodified HACS installation, clean-user setup and
reauthentication usability, and a real delivery lifecycle remain gates in #42.
