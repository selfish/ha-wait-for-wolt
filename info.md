# Wait for Wolt

Wait for Wolt is an unofficial Home Assistant integration for active Wolt
deliveries. It creates stable status and estimated-arrival sensors for each
active purchase, refreshes saved credentials when needed, and can optionally
monitor selected venues for availability and delivery estimates. It does not
expose order contents, payment details, addresses, or raw Wolt responses as
entity attributes.

Configure the integration from the Home Assistant UI using an access token and
refresh token obtained from wolt.com. The analytics session ID is optional.
Venue IDs correspond to the slug in the venue URL, for example `mententen` in
`https://wolt.com/en/isr/tel-aviv/restaurant/mententen`. When configuring via the UI, place each ID on its own line.

