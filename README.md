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
2. Under the **Application** (or **Storage**) tab locate the **Local
   Storage** entry for `https://wolt.com`.
3. In the **Console** paste the snippet below to print the needed values
   without digging through the storage menus:

   ```js
   (() => {
     const session = localStorage.getItem('__woltUid');
     const access = JSON.parse(localStorage.getItem('__wtoken') || '{}').accessToken;
     const refresh = decodeURIComponent(document.cookie.match(/__wrtoken=([^;]+)/)?.[1] || '');
     console.log('SESSION_ID:', session);
     console.log('ACCESS_TOKEN:', access);
     console.log('REFRESH_TOKEN:', refresh);
   })();
   ```

   Copy the printed values for use below. If the keys are not present you can
   also inspect the network request headers to find them.
4. Use these tokens in the configuration below. They will be refreshed
   automatically when required.


## Configuration
You can add the integration from Home Assistant's **Add Integration** menu or via YAML.
To configure with YAML, add a sensor entry to `configuration.yaml`:

```yaml
sensor:
  - platform: wait_for_wolt
    name: My Wolt Account
    session_id: YOUR_SESSION_ID
    bearer_token: YOUR_ACCESS_TOKEN
    refresh_token: YOUR_REFRESH_TOKEN
```

## How it works
- The integration refreshes the bearer token automatically.
- Every minute it polls Wolt for your active orders.
- A sensor entity is created for each order that is in progress. The sensor state reflects the current order status and attributes include the delivery estimate, venue and items ordered.
- New orders placed while Home Assistant is running are discovered automatically within the polling interval.

## Limitations
- The integration relies on tokens taken from the Wolt web site. If they become invalid you will need to capture new ones.
