# Changelog

All notable changes to Wolt Order Tracker will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Offline Home Assistant tests with synthetic fixtures.
- Ruff, locked Python tooling, Hassfest, HACS validation, Dependabot, and exact-commit review packages.
- MIT license and contributor/security guidance.

### Changed

- Wolt analytics session ID is optional.
- Active-order discovery accepts Wolt's current `purchase_id` field.
- Access tokens are refreshed only after an unauthorized response, using Wolt's current web refresh flow.

### Security

- Rotated credentials are persisted without being logged.
- Documentation and tests explicitly prohibit real Wolt or Home Assistant secrets.

[Unreleased]: https://github.com/selfish/ha-wait-for-wolt/compare/main...HEAD
