# Migration from unreleased installations

The first beta is a canonical rewrite of several unreleased local and commit-based builds. Make a Home Assistant backup before upgrading and follow [CANARY.md](CANARY.md).

## Preserved behavior

- Existing YAML credentials are imported into a durable UI config entry.
- Rotated tokens are stored in the config entry.
- Legacy order unique IDs (`wolt_<purchase>`) migrate to config-entry-scoped status IDs while preserving entity-registry customizations.
- Existing scoped final-order entities are restored after restart when Wolt still returns the order summary.
- Optional venue monitoring remains available.
- Both observed purchase-tracking URL forms are supported: query parameter first, then a path-form fallback after `404` or `405`.

## Intentional safety changes

- The old mixed order sensor becomes a normalized enum status sensor; ETA is a separate timestamp sensor. Automations that compared duration text must be updated.
- Raw item, payment, address, order-history, and tracking payload attributes are removed.
- The one captured web-client identifier formerly shipped to every installation is replaced by a random identifier persisted per config entry.
- Setup and reauthentication validate credentials before saving them. A refresh token can bootstrap the access token.

## Explicitly deferred experimental behavior

The recovered local `0.0.5` component remains rollback evidence, not publication source. These behaviors are deliberately excluded from the first beta:

| Recovered behavior | Decision | Reason / safer direction |
|---|---|---|
| Consumer-events websocket | Deferred | Current room/auth/event contracts need sanitized evidence plus bounded reconnect, clean unload, and polling fallback tests. Thirty-second active polling remains the correctness path. |
| Courier coordinates and route points | Deferred | High-frequency location history has recorder/privacy consequences. Any future entity must be opt-in with explicit recorder guidance and no route-history attributes. |
| Monthly spending | Deferred | Financial/order-history collection is outside delivery automation scope and risks long-lived private history in Home Assistant. Local analytics tools such as `mekedron/wolt-cli` and `wolt-stats` are a better ecosystem fit. |
| Minutes-to-arrival text | Replaced | An explicit Wolt timestamp becomes a typed ETA sensor. Duration-like values are not guessed into timestamps. |
| Rich item/payment attributes | Removed | They are unnecessary for arrival automations and unsafe in recorder, diagnostics, and issue reports. |
| Extra venue scraping | Deferred | Only the current sanitized public venue contract is retained. Fee/estimate redesign waits for stable structured amount/unit fields rather than parsing localized display strings. |

Deferred entities are not deleted from the Home Assistant entity registry. They may become unavailable after upgrade, allowing a rollback to restore their implementation. Users may remove them manually only after deciding they no longer need rollback compatibility.

## Authentication boundary

Wolt's current web email and phone flows use private endpoints and hCaptcha-protected operations. There is no published consumer OAuth or device flow that Home Assistant can register for. The integration therefore does not collect phone numbers, email addresses, OTPs, passwords, or magic links. It accepts the browser-derived refresh credential and rotates it through Wolt's access-token endpoint.

This boundary should change only if Wolt publishes an authorized consumer flow or a browser-mediated handoff can be implemented without bypassing captcha, exposing credentials, or embedding an unsupported browser runtime in Home Assistant.
