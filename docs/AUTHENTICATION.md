# Authentication design

Wait for Wolt uses Wolt's undocumented consumer web API. Wolt does not publish an OAuth client, device-code flow, or supported consumer API for Home Assistant integrations.

## Supported beta flow

The beta accepts a Wolt refresh token. An access token and analytics session ID are optional.

During setup or reauthentication the integration:

1. generates and persists one non-secret web-client identifier for the config entry;
2. exchanges the refresh token when no access token was supplied;
3. performs an authenticated order-list request before saving the entry;
4. stores every rotated access and refresh token immediately; and
5. redacts all credentials and client/session identifiers from diagnostics.

A refresh token grants access to private Wolt account data. Treat it like a password. Never put it in issues, logs, screenshots, diagnostics, fixtures, or automation YAML.

## Why phone/email login is not embedded

Wolt's current website supports email, SMS/phone, Google, and Facebook authentication, but those are private web flows rather than a public third-party authorization contract. The observed email and phone paths include CAPTCHA, access-confirmation, and OTP/magic-link branches. Replaying them from a headless Home Assistant server would bypass the first-party browser context and make the integration responsible for anti-abuse behavior and sensitive phone/email handling.

The project therefore does **not** send OTPs, collect Wolt passwords, imitate CAPTCHA, or ask users to forward magic links. A server-side clone of those private flows is not considered publication-ready authentication.

## Browser-mediated direction

The preferred future design is a browser-mediated helper that:

- opens Wolt's real login page in an isolated local browser profile;
- lets Wolt own email/phone, CAPTCHA, OTP, and access confirmation;
- returns only the resulting refresh credential through a short-lived local handoff;
- never routes credentials through a third-party service; and
- requires explicit confirmation before Home Assistant stores the result.

The maintained open-source [`mekedron/wolt-cli`](https://github.com/mekedron/wolt-cli) demonstrates this general approach by opening a managed local browser instead of cloning Wolt's OTP protocol. Its login mechanism cannot be embedded directly in a HACS integration because Home Assistant OS does not provide Chrome/Chromium and HACS integrations cannot depend on an external Go binary. Reuse should therefore happen through a separately reviewed helper or upstream handoff protocol, not by copying browser automation into the integration.

Until such a helper is designed and security-reviewed, refresh-token-only setup is the supported compromise.
