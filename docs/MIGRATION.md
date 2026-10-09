# Upgrading to 0.1.0b2

Back up the installed component and keep config entries and the entity registry.
This beta follows the first packaged release; older commit-based builds were not releases.

## Preserved contracts

- `wolt_<purchase>` stays a **numeric duration in minutes**, migrating to the
  entry-scoped delivery ID. Its entity ID, custom name and disabled state survive.
- Status and timestamp ETA have distinct identities. A partial-upgrade collision
  preserves both delivery registry records rather than overwriting either.
- Pickup/destination legacy identities remain owned by their original entry.
- Delivery sensors retain the `sensor.wolt_delivery_` naming prefix for dashboards.
- New orders appear automatically. Terminal/vanished orders cannot retain minutes,
  arrival flags or courier coordinates; rich polling stops when an order ends.
- Existing venue sensors and persisted rotating credentials remain supported.

## Privacy and map options

Delivery minutes do not require location permission. A legacy location authorizes
only that entity and that order—not unrelated entities, other accounts or future
orders. Explicitly disabling locations overrides inherited consent.

To track locations on future orders, enable **Location attributes** in Configure.
The destination marker uses only Wolt's actual GeoJSON dropoff coordinates, marked
`coordinate_source: wolt_dropoff`; it no longer offers a Home-zone substitute.
Consider excluding location entities from Recorder.

Raw orders, addresses, item lists, payment instruments and courier identity are
not published. New per-order total and fee entities are disabled by default;
product quantity is available without publishing item names. Existing private
Recorder history is not automatically purged.

## Deliberate limits

- Courier updates use the shared 30-second poll, not a consumer-events websocket.
- Optional tracking failure keeps the order summary working and uses backoff.
- Dropoff events are published only when explicitly reported; none are invented
  from ETA or distance. Arrival automation should use a valid ETA/minutes fallback.
- Authentication still needs a browser-derived refresh token; there is no public
  consumer OAuth flow, and no CAPTCHA bypass or credential scraping is provided.

## Rollback

Preserve the preceding component outside `custom_components`. Restore those files
and restart HA if needed. Never restore stale refresh tokens after rotation. For
legacy code that understands only old unique IDs, reverse only this entry's ID
migrations from the private registry backup; do not replace unrelated registry data.
Do not delete the integration or its entities to troubleshoot an upgrade.
