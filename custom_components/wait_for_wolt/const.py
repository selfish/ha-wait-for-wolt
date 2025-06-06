"""Constants for the Wolt order tracker."""

DOMAIN = "wait_for_wolt"

CONF_SESSION_ID = "session_id"
CONF_BEARER_TOKEN = "bearer_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_VENUE_IDS = "venue_ids"

DEFAULT_NAME = "Wolt Order"

UPDATE_INTERVAL = 60  # seconds

REFRESH_URL = "https://restaurant-api.wolt.com/v3/auth/token"
ACTIVE_ORDERS_URL = "https://restaurant-api.wolt.com/v2/orders/active"
ORDER_DETAILS_URL = (
    "https://restaurant-api.wolt.com/v2/order_details/by_ids?purchases={}")
VENUE_CONTENT_URL = (
    "https://consumer-api.wolt.com/consumer-api/venue-content-api/v3/web/venue-content/slug/{}"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:138.0) Gecko/20100101 Firefox/138.0",
    "Accept": "application/json, text/plain, */*",
    "Platform": "Web",
    "App-Language": "en",
    "ClientVersionNumber": "1.15.28",
    "Client-Version": "1.15.28",
    "App-Currency-Format": "wqQxLDIzNC41Ng==",
    "x-wolt-web-clientid": "76cc0f70-9891-4c90-ab38-e6b5fdab4c02",
}
