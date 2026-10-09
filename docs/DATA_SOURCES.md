# Wolt data sources and semantics

Read-only audit: 2026-09-25. These are private endpoints, not a supported Wolt API.
Only field shapes and aggregate validation outcomes were retained; no credentials,
customer payloads, purchase IDs or coordinates belong in this repository.

## Endpoints exercised

- `GET https://consumer-api.wolt.com/order-xp/web/v1/pages/orders`: HTTP 200;
  50 recent summaries, no active order at audit time. `purchase_id` identifies a
  purchase; `telemetry.order_status_type` remains the lifecycle authority.
- `GET https://restaurant-api.wolt.com/v2/order_details/purchase_tracking/{purchase_id}`:
  HTTP 200 for a recent completed purchase. The query-parameter form returned 404.
  The integration now prefers the path form, with the query variant as a bounded
  404/405 fallback. Completed details were inspected only for this audit; normal
  polling requests rich details only for active orders.
- Public venue dynamic endpoint: HTTP 200. Delivery availability and estimates
  remain on the configured venue entity; absent availability is unknown, not closed.

## Canonical entities

- **Status and ETA:** preserve normalized status, telemetry-presence semantics,
  explicit timestamp parsing and driver-to-order ETA fallback. Localized summary
  date strings are not reliable timeline timestamps and are not parsed.
- **Delivery minutes:** preserves legacy identity/name/customizations, route
  metadata, explicit event allowlist and the at-most-three-minute arrival window.
  A stale estimate is not an arrival event. Courier assignment and heading remain
  attributes; no invented progress percentage or extra event is inferred.
- **Item count:** sum `items[].count`, excluding option quantities. Invalid or
  missing quantities yield unknown, not a guessed number of array entries. This
  describes product quantities, not weights or a count of modifiers.
- **Order total (disabled by default):** `telemetry.end_amount` is integer minor
  units, verified against the displayed total for all 50 audited summaries.
  Only unambiguous observed ILS/EUR display formats are accepted; other formats
  remain unknown. Do not substitute `total_price_share`, discounts or credits.
- **Delivery fee / service fee (disabled by default):** integer `delivery_price`
  and `service_fee` from `order_details`, with an explicit recognized `currency`.
  Missing, malformed, negative or ambiguous amounts remain unknown. These are
  active-order facts, not account aggregates, and clear when rich data disappears.
- **Pickup/dropoff (location opt-in):** preserve pickup venue coordinates and read
  the actual dropoff from `delivery_location.coordinates`, a GeoJSON Point with
  longitude first. Only validated coordinates are exposed, never address fields.
  Home Assistant's Home zone is not used as a substitute. Existing per-entity,
  per-order consent, disabled settings and explicit opt-out remain authoritative.

`payment_time.$date` is a status attribute when it is a valid timestamp. Raw
payment/group/customer objects, delivery instructions and item descriptions are
not entity attributes or diagnostic output.

## Verification boundary

Synthetic lifecycle tests cover active/terminal/vanished orders, malformed facts,
currency units, location consent and privacy. The live audit had no active order
and no courier payload; it does **not** verify live courier motion, ETA changes,
arrival/dropoff event delivery, or an end-to-end delivery. Those checks remain for
the next real order. No websocket connection or event synthesis was added.
