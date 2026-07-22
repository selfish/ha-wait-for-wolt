# Security policy

## Supported versions

Until the first stable release, only the latest release and the current `main` branch receive security fixes.

## Reporting a vulnerability

Use GitHub's **Report a vulnerability** option on the repository Security tab whenever it is available. Do not disclose a vulnerability publicly before a fix is ready.

If private reporting is unavailable, open a minimal issue asking the maintainer for a private contact channel. Do **not** include exploit details, Wolt cookies or tokens, Home Assistant credentials, addresses, order data, courier locations, HAR files, screenshots containing account data, or logs containing secrets.

Include, through the private channel:

- the affected integration version or commit;
- the Home Assistant version;
- impact and reproducible steps using synthetic/redacted values;
- any suggested mitigation.

You should receive an acknowledgement within seven days. Timing for a fix and disclosure will depend on severity and whether the issue originates in this integration or Wolt's private consumer API.

## Credential handling

Treat Wolt access tokens, refresh tokens, session cookies, Home Assistant tokens, and captured browser traffic as passwords. The project will never ask you to post them in a public issue, test fixture, pull request, or chat.
