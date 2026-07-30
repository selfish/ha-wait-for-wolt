# Canary and rollback matrix

No production installation is the first consumer of a release artifact.

## Automated layers

1. **Synthetic unit and Home Assistant harness tests** cover API error mapping, token rotation, setup retry, reauthentication, unload/reload, options updates, multiple and finished orders, status transitions, diagnostics redaction, entity restoration, and legacy unique-ID migration.
2. **Hassfest and HACS Action** validate Home Assistant and repository structure. HACS validation must run without ignored checks.
3. **Exact-commit package** is built only after the preceding jobs pass. Its SHA-256 checksum and commit metadata are stored with the archive.
4. **Disposable container canary** extracts that archive, runs Home Assistant `check_config`, starts the pinned supported Home Assistant image, waits for HTTP readiness, and scans for integration startup errors:

   ```bash
   scripts/canary.sh
   ```

Set `HA_IMAGE` to repeat against another supported Home Assistant image.

## Operational canary

Use a disposable Home Assistant instance or a clone with recorder and outbound notifications disabled. Never upload its `.storage` files or logs.

Record pass/fail for:

- fresh HACS custom-repository installation from a full GitHub release;
- upgrade from the preceding release;
- restart, unload, reload, and option-only update;
- refresh-token-only setup;
- rejected-token reauthentication and recovery;
- idle account with no active orders;
- one active delivery through its terminal state;
- two synthetic/safely observed simultaneous orders if available;
- configured open and closed venue slugs;
- Wolt timeout, malformed payload, 401/403, and 429 recovery through the offline suite;
- rollback to the preceding component without deleting config entries or entity-registry data.

Only normalized states, timestamps, counts, exception classes, versions, and pass/fail results may leave the canary. Do not capture account names, tokens, order/purchase IDs, addresses, items, prices, courier coordinates, raw payloads, or `.storage` files.

## Production rollout

1. Create a Home Assistant backup.
2. Preserve the currently installed `custom_components/wait_for_wolt` directory outside the config directory and calculate its checksum.
3. Keep config entries and entity-registry data in place.
4. Install the canary-approved artifact and restart.
5. Observe one idle cycle and, when practical, one real active-order lifecycle.
6. If a release gate fails, restore the previous component directory or preceding HACS release and restart. Do not delete entities or the config entry; rollback relies on their preserved registry identities.

A beta may ship for opt-in feedback after offline/container checks. A stable release additionally requires the operational canary and rollback rows above.
