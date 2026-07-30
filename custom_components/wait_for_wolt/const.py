"""Constants for the Wolt order tracker."""

DOMAIN = "wait_for_wolt"

CONF_SESSION_ID = "session_id"
CONF_BEARER_TOKEN = "bearer_token"
CONF_CLIENT_ID = "client_id"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_VENUE_IDS = "venue_ids"

DEFAULT_NAME = "Wolt Order"

REFRESH_URL = "https://authentication.wolt.com/v1/wauth2/access_token"
# Updated endpoints based on the current Wolt web client
ACTIVE_ORDERS_URL = "https://consumer-api.wolt.com/order-xp/web/v1/pages/orders"
ORDER_DETAILS_URL = (
    "https://restaurant-api.wolt.com/v2/order_details/purchase_tracking?purchase_id={}"
)
ORDER_DETAILS_PATH_URL = (
    "https://restaurant-api.wolt.com/v2/order_details/purchase_tracking/{}"
)
VENUE_CONTENT_URL = "https://consumer-api.wolt.com/order-xp/web/v1/venue/slug/{}/dynamic/?selected_delivery_method=homedelivery"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:138.0) Gecko/20100101 Firefox/138.0",
    "Accept": "application/json, text/plain, */*",
    "Platform": "Web",
    "App-Language": "en",
    "ClientVersionNumber": "1.16.79",
    "Client-Version": "1.16.79",
    "App-Currency-Format": "wqQxLDIzNC41Ng==",
}
