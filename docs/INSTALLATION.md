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

## Verified manual fallback

Use a release ZIP, never a working checkout or GitHub's **Source code (zip)**.
The fixed-name `wait_for_wolt.zip` contains component files at its root.

1. Make a Home Assistant backup and preserve the currently installed component
   outside its active `custom_components` directory. Keep the config entry,
   entity registry and device registry intact. Treat backups as secrets.
2. Download the ZIP and checksum from the **same**
   [release](https://github.com/selfish/ha-wait-for-wolt/releases). For b2, run
   these commands in a new local directory:

   ```bash
   gh release download v0.1.0b2 --repo selfish/ha-wait-for-wolt \
     --pattern wait_for_wolt.zip --pattern wait_for_wolt.sha256
   sha256sum --check wait_for_wolt.sha256
   ```

   Stop on any checksum mismatch. The checksum verifies artifact consistency;
   it is not an independent publisher signature.
3. Extract into a staging directory. Confirm `manifest.json` names the
   `wait_for_wolt` domain and expected version (`0.1.0b2` for this release).
   Do not introduce another nested `wait_for_wolt` directory.
4. Replace only `/config/custom_components/wait_for_wolt` with the staged
   component, using the filesystem access supported by your HA installation.
   Compare every installed file against the ZIP and check for leftover files
   from previous versions. Do not edit `.storage` or HACS's version ledger.
   If an SSH add-on lacks SFTP and `scp` reports that subsystem failure,
   OpenSSH's `scp -O` uses legacy SCP over the same SSH connection; retain host-key
   checking. This is a transport fallback, not a reason to bypass approvals.
5. Run Home Assistant's configuration check, then restart. A restart can close
   the API connection before returning a response: check readiness and new
   startup logs rather than repeatedly issuing restarts.
6. Verify the Wait for Wolt config entry is loaded, venue polling succeeds and
   new startup logs contain no integration errors. With no active order,
   absent order entities are normal. See the [canary matrix](CANARY.md) for
   remaining real-order and rollback gates.

Manual installation does not update HACS's own `installed_version`. Its update
entity may still show b1 even when the loaded component is b2. Confirm the loaded
integration's startup version and installed-file hashes; do not mistake the HACS
ledger for runtime evidence. Reconcile via a successful supported HACS installation
when its download path is repaired, not by editing HACS's private storage.

## Current verification boundary

The b2 production component was installed byte-for-byte from the published ZIP;
configuration validation, restart, loaded integration, idle polling and venue
polling passed. That is **not** proof of a successful HACS-managed installation
or a real delivery lifecycle. Those remain independent operational gates.
