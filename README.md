# ha-wait-for-wolt

This custom component tracks your Wolt orders in Home Assistant. It polls the Wolt API using tokens that you obtain once from the web site and keeps them refreshed automatically.

## Installation via HACS
1. Add this repository as a custom repository in [HACS](https://hacs.xyz/).
2. Install **Wolt Order Tracker** and restart Home Assistant.

## Getting your tokens
Tokens are required to authenticate with the Wolt API. The easiest way to
capture them is from your web browser after logging in.

1. Log in to [wolt.com](https://wolt.com) and open the developer tools
   (usually <kbd>F12</kbd> or <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>I</kbd>).
2. Under the **Application** (or **Storage**) tab, open the cookies for
   `https://wolt.com`.
3. In the **Console** paste the snippet below to print the needed values
   without digging through the storage menus:

   ```js
   (() => {
     const getCookie = (name) => document.cookie.split('; ').find(row => row.startsWith(name + '='))?.split('=')[1];
     const decode = (name) => {
       const raw = getCookie(name);
       if (!raw) return undefined;
       try { return JSON.parse(decodeURIComponent(raw)); }
       catch { return decodeURIComponent(raw); }
     };
     const access = decode('__wtoken');
     const refresh = decode('__wrtoken');
     console.log('SESSION_ID (optional):', getCookie('__woltUid'));
     console.log('ACCESS_TOKEN:', access?.accessToken ?? access?.access_token ?? access);
     console.log('REFRESH_TOKEN:', refresh?.refreshToken ?? refresh?.refresh_token ?? refresh);
   })();
   ```

   Copy the access and refresh tokens for use below. `SESSION_ID` is optional:
   accounts without analytics consent may not have `__woltUid`, and authenticated
   order requests work without that header. If a token is not printed, inspect an
   authenticated Wolt network request instead.
4. Use these tokens in the configuration below. They will be refreshed
   automatically when required.


## Configuration
You can add the integration from Home Assistant's **Add Integration** menu or via YAML.
To configure with YAML, add a sensor entry to `configuration.yaml`:

```yaml
sensor:
  - platform: wait_for_wolt
    name: My Wolt Account
    # Optional; omit if Wolt does not expose __woltUid.
    session_id: YOUR_SESSION_ID
    bearer_token: YOUR_ACCESS_TOKEN
    refresh_token: YOUR_REFRESH_TOKEN
    venue_ids:
      - mententen
      - another-venue
```

`venue_ids` should be the slug from the venue URL on wolt.com. For example,
`https://wolt.com/en/isr/tel-aviv/restaurant/mententen` uses `mententen` as the
ID. Enter one ID per line or list entry. When configuring from the UI, type each
ID on a new line.

## How it works
- The integration refreshes the bearer token automatically.
- Every minute it polls Wolt for your active orders.
- A sensor entity is created for each order that is in progress. The sensor state reflects the current order status and attributes include the delivery estimate, venue and items ordered.
- New orders placed while Home Assistant is running are discovered automatically within the polling interval.
- If you configure `venue_ids`, sensors for each venue report whether it is open and expose delivery price and estimates when available.

## Limitations
- This is an unofficial integration and is not affiliated with or endorsed by Wolt.
- It relies on Wolt's private consumer web API, which can change without notice.
- If both the access and refresh tokens become invalid, you will need to capture new ones.
- Treat every cookie and token as a password. Never post them in an issue, log, screenshot, or test fixture.

## Development

See [Development and verification](docs/DEVELOPMENT.md) for locked setup commands,
sanitized-fixture rules, CI validation, and exact-commit review artifacts. Contributions
must follow the [contributor guide](CONTRIBUTING.md) and [security policy](SECURITY.md).
Release-facing changes are recorded in the [changelog](CHANGELOG.md).
