# ha-wait-for-wolt

This custom component tracks your Wolt orders in Home Assistant. It polls the Wolt API using tokens that you obtain once from the web site and keeps them refreshed automatically.

## Installation via HACS
1. Add this repository as a custom repository in [HACS](https://hacs.xyz/).
2. Install **Wolt Order Tracker** and restart Home Assistant.

## Getting your tokens
1. Log in to [wolt.com](https://wolt.com) in a browser.
2. Inspect the network requests or local storage and copy the values of `w-wolt-session-id`, `access_token` and `refresh_token`.
3. Use these values in the configuration below. The integration will refresh the access token when needed using the refresh token.

## Configuration
Add a sensor entry to `configuration.yaml`:

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
