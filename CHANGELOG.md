# Changelog

All notable changes to Wolt Order Tracker will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Offline Home Assistant tests with synthetic fixtures.
- Ruff, locked Python tooling, Hassfest, HACS validation, Dependabot, and exact-commit review packages.
- MIT license and contributor/security guidance.
- A Home Assistant-independent Wolt API client with typed authentication,
  connectivity, rate-limit, and payload errors.
- Rich purchase-tracking endpoint support with current and legacy response-shape
  compatibility.
- A shared `DataUpdateCoordinator` with dynamic order discovery and Home
  Assistant reauthentication support.
- Privacy-preserving diagnostics that expose operational counts without order,
  courier, venue, account-name, or credential values.
- Typed per-purchase status and ETA entities with English and Hebrew UI translations.

### Changed

- Wolt analytics session ID is optional.
- Active-order discovery accepts Wolt's current `purchase_id` field.
- Access tokens are refreshed only after an unauthorized response, using Wolt's current web refresh flow.
- Completed order history is filtered out before entities are created.
- Legacy YAML configuration is imported once into a durable config entry and is
  deprecated as a runtime credential source.
- The minimum supported Home Assistant version is now 2026.7.0, matching the
  tested Python and Home Assistant environment.
- Authenticated polling adapts from five minutes while idle to 30 seconds while
  an order is active; venue polling uses a conservative five-minute interval.
- Credential inputs are password-masked, and options no longer prefill saved
  access or refresh tokens.
- Order status entities use stable normalized enum values, config-entry-scoped
  unique IDs, and a shared per-purchase device.

### Fixed

- Credential-only options edits now reload the running API client.
- Concurrent unauthorized requests share one serialized token refresh instead
  of racing rotating refresh tokens.
- Malformed JSON responses become typed payload errors instead of escaping the
  integration update path.
- Optional rich tracking failures now preserve the usable order summary instead
  of making every order entity unavailable.
- Venue sensors now preserve an explicit closed status even when broader venue
  metadata still reports the venue online.
- Authoritative telemetry states other than `IN_PROGRESS` can no longer fall
  through to legacy heuristics and create false active-order entities.
- Loaded-entry reauthentication now schedules exactly one reload instead of
  duplicating the immediate post-credential-update polling cycle.
- Existing order status entities migrate to the scoped identity without losing
  entity-registry customizations.

### Security

- Rotated credentials are persisted without being logged.
- Documentation and tests explicitly prohibit real Wolt or Home Assistant secrets.
- Venue-update warnings no longer include configured venue slugs.
- Order entities no longer expose item lists, payment values, addresses, or raw
  tracking payloads as state attributes.

[Unreleased]: https://github.com/selfish/ha-wait-for-wolt/compare/main...HEAD
