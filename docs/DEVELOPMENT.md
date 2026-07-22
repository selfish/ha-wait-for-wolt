# Development and verification

The test suite is intentionally offline. It must never contact Wolt or require a real
Home Assistant account.

## Prerequisites

- [uv](https://docs.astral.sh/uv/); uv installs the locked Python runtime when needed.
- Docker, only for the optional local Hassfest command.

## Clean-checkout commands

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Hassfest can also be run with the same official container used by Home Assistant's
GitHub Action:

```bash
docker run --rm \
  -v "$PWD/custom_components:/github/workspace/custom_components:ro" \
  ghcr.io/home-assistant/hassfest
```

The pull-request workflow runs all commands above plus the official HACS repository
validation action. CI action revisions and Python dependencies are pinned; Dependabot
maintains both groups monthly.

HACS brand and repository-topic checks are temporarily ignored because the repository
has no approved brand asset and the automation App cannot edit repository topics. On
pull requests, the workflow verifies the reviewed MIT `LICENSE` file directly because
HACS reads license metadata from the default branch; after merge, the push workflow
validates the repository's detected license through HACS as well.

## Fixture privacy rules

All files in `tests/fixtures/` must be synthetic and reviewable as public data.
Never copy a browser response or Home Assistant storage file into the repository.
Fixtures and test output must not contain:

- cookies, access tokens, refresh tokens, or real session IDs;
- names, phone numbers, email addresses, or delivery addresses;
- account, payment, courier, order, or venue-owner identifiers;
- real order contents, prices, timestamps, or location data.

Use conspicuous values such as `sanitized-order-001`, `sanitized-session-id`, and
`Sanitized Test Venue`. Before committing, inspect the complete staged diff rather
than relying only on automated secret scanning.

## Review artifact

After tests, Hassfest, and HACS validation pass, CI packages the exact pull-request
head commit as `wait_for_wolt-<commit>.zip`. The workflow artifact also includes:

- `wait_for_wolt-<commit>.sha256`, containing the SHA-256 checksum;
- `wait_for_wolt-<commit>.metadata`, identifying the source commit.

The artifact is for manual review in a disposable Home Assistant instance. CI does
not install it, publish a release, or modify a live Home Assistant system.
