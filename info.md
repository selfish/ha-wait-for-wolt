# Wolt Order Tracker

Track your Wolt deliveries in Home Assistant. You can configure the integration from the UI or provide an access token and refresh token in YAML. The analytics session ID is optional. The integration refreshes credentials only when Wolt rejects the access token and creates sensors for active orders. You can also monitor venues by adding their IDs to get open/closed status.
Venue IDs correspond to the slug in the venue URL, for example `mententen` in
`https://wolt.com/en/isr/tel-aviv/restaurant/mententen`. When configuring via the UI, place each ID on its own line.

