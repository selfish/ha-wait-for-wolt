# Contributing

Thanks for helping improve Wolt Order Tracker. This is an unofficial Home Assistant integration built on Wolt's private consumer web API, so reliability, privacy, and conservative request behavior are core requirements.

## Before opening a change

- Search existing issues and pull requests.
- For API-contract changes, describe the observed behavior without sharing account data or credentials.
- Keep changes focused. Large architecture changes should start with an issue.

## Local setup

Install [uv](https://docs.astral.sh/uv/), then run:

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

See [Development and verification](docs/DEVELOPMENT.md) for the full workflow and exact-commit review artifacts.

## Privacy rules

Never commit or paste real:

- Wolt access or refresh tokens;
- cookies, session identifiers, HAR files, or authorization headers;
- names, phone numbers, addresses, order IDs, purchase IDs, courier coordinates, or item histories;
- Home Assistant URLs, tokens, diagnostics containing credentials, or entity-registry exports.

Tests must use minimal synthetic fixtures with obviously fake values such as `sanitized-purchase-001`. Reduce real payloads to the smallest synthetic shape needed to reproduce the behavior.

## Code and architecture

- Follow current Home Assistant integration patterns.
- Keep network logic in the API client and shared polling in a `DataUpdateCoordinator`.
- Classify authentication, connectivity, rate-limit, and payload errors explicitly.
- Do not log tokens or full API payloads.
- Preserve stable entity unique IDs and include migration tests for changes.
- Keep polling conservative; Wolt does not publish a supported API for this use.
- Add tests before or alongside behavior changes.

## Pull requests

A pull request should explain the problem, the approach, privacy considerations, and real verification performed. CI must pass Ruff, pytest, Hassfest, HACS validation, and exact-commit packaging before merge.

By contributing, you agree that your contribution is licensed under the repository's MIT license.
