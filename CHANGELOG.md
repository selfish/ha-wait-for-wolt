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

### Changed

- Wolt analytics session ID is optional.
- Active-order discovery accepts Wolt's current `purchase_id` field.
- Access tokens are refreshed only after an unauthorized response, using Wolt's current web refresh flow.
- Completed order history is filtered out before entities are created.
- Legacy YAML configuration is imported once into a durable config entry and is
  deprecated as a runtime credential source.
- The minimum supported Home Assistant version is now 2026.7.0, matching the
  tested Python and Home Assistant environment.

### Fixed

- Credential-only options edits now reload the running API client.
- Concurrent unauthorized requests share one serialized token refresh instead
  of racing rotating refresh tokens.
- Malformed JSON responses become typed payload errors instead of escaping the
  integration update path.

### Security

- Rotated credentials are persisted without being logged.
- Documentation and tests explicitly prohibit real Wolt or Home Assistant secrets.

[Unreleased]: https://github.com/selfish/ha-wait-for-wolt/compare/main...HEAD
