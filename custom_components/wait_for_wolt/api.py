"""Home Assistant-independent asynchronous client for Wolt endpoints."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import (
    ACTIVE_ORDERS_URL,
    HEADERS,
    ORDER_DETAILS_URL,
    REFRESH_URL,
    VENUE_CONTENT_URL,
)

REQUEST_TIMEOUT = 10

TokenUpdateCallback = Callable[[str, str], Awaitable[None] | None]


def is_active_order(order: dict[str, Any]) -> bool:
    """Return whether an order-list item represents a trackable active order."""
    telemetry = order.get("telemetry")
    status_type = (
        telemetry.get("order_status_type")
        if isinstance(telemetry, dict)
        else order.get("order_status_type")
    )
    if status_type is not None:
        # Current Wolt order-list payloads provide an authoritative telemetry
        # state. Do not let legacy CTA/text heuristics override any non-active
        # telemetry value such as COMPLETED or PENDING.
        return str(status_type).upper() == "IN_PROGRESS"

    call_to_action = order.get("call_to_action")
    if isinstance(call_to_action, dict):
        action = call_to_action.get("link") or call_to_action.get("type")
        if action and "ORDER_TRACKING" in str(action).upper():
            return True

    status = order.get("status")
    if isinstance(status, dict):
        status = status.get("value") or status.get("text") or status.get("label")
    if not isinstance(status, str) or not status:
        return False
    return not any(
        final_word in status.lower()
        for final_word in ("delivered", "cancel", "failed", "refunded", "rejected")
    )


class WoltApiError(Exception):
    """Base class for Wolt API failures."""


class WoltAuthenticationError(WoltApiError):
    """The access or refresh credentials were rejected."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class WoltConnectionError(WoltApiError):
    """Wolt could not be reached or returned an unsuccessful response."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class WoltRateLimitError(WoltConnectionError):
    """Wolt rejected a request because its rate limit was reached."""


class WoltInvalidPayloadError(WoltApiError):
    """Wolt returned JSON with an incompatible shape."""


class WoltApi:
    """Asynchronous client for the Wolt endpoints used by this integration."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        session_id: str | None,
        access_token: str,
        refresh_token: str,
        *,
        token_update_callback: TokenUpdateCallback | None = None,
    ) -> None:
        self._session = session
        self._session_id = session_id
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_update_callback = token_update_callback
        self._refresh_lock = asyncio.Lock()

    @property
    def access_token(self) -> str:
        """Return the currently active access token."""
        return self._access_token

    @property
    def refresh_token(self) -> str:
        """Return the currently active refresh token."""
        return self._refresh_token

    def _headers(self, *, authenticated: bool) -> dict[str, str]:
        """Build fresh request headers without mutating shared constants."""
        headers = dict(HEADERS)
        if authenticated:
            headers["authorization"] = f"Bearer {self._access_token}"
            if self._session_id:
                headers["w-wolt-session-id"] = self._session_id
        return headers

    async def _perform_request(
        self,
        method: str,
        url: str,
        *,
        authenticated: bool,
        data: dict[str, str] | None = None,
    ) -> Any:
        """Perform one request and translate transport/status/payload failures."""
        headers = self._headers(authenticated=authenticated)
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                if method == "POST":
                    request = self._session.post(url, headers=headers, data=data)
                else:
                    request = self._session.request(method, url, headers=headers)
                async with request as response:
                    if response.status in (401, 403):
                        raise WoltAuthenticationError(
                            "Wolt rejected the supplied credentials",
                            status=response.status,
                        )
                    if response.status == 429:
                        raise WoltRateLimitError("Wolt rate limit reached")
                    if response.status >= 400:
                        raise WoltConnectionError(
                            f"Wolt request failed with status {response.status}",
                            status=response.status,
                        )
                    try:
                        return await response.json()
                    except (aiohttp.ContentTypeError, TypeError, ValueError) as err:
                        raise WoltInvalidPayloadError(
                            "Wolt returned invalid JSON"
                        ) from err
        except WoltApiError, asyncio.CancelledError:
            raise
        except (TimeoutError, aiohttp.ClientError) as err:
            raise WoltConnectionError("Unable to connect to Wolt") from err

    async def _refresh_access_token(self) -> None:
        """Refresh credentials with Wolt's form-encoded web authentication flow."""
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }
        try:
            data = await self._perform_request(
                "POST",
                REFRESH_URL,
                authenticated=False,
                data=payload,
            )
        except WoltConnectionError as err:
            if err.status == 400:
                raise WoltAuthenticationError(
                    "Wolt rejected the supplied refresh token", status=err.status
                ) from err
            raise
        if not isinstance(data, dict):
            raise WoltInvalidPayloadError("Wolt token refresh returned a non-object")

        access_token = data.get("access_token") or data.get("accessToken")
        if not isinstance(access_token, str) or not access_token:
            raise WoltInvalidPayloadError(
                "Wolt token refresh did not return an access token"
            )

        refresh_token = data.get("refresh_token") or data.get("refreshToken")
        if refresh_token is None:
            refresh_token = self._refresh_token
        if not isinstance(refresh_token, str) or not refresh_token:
            raise WoltInvalidPayloadError(
                "Wolt token refresh returned an invalid refresh token"
            )

        self._access_token = access_token
        self._refresh_token = refresh_token

        if self._token_update_callback is not None:
            callback_result = self._token_update_callback(access_token, refresh_token)
            if inspect.isawaitable(callback_result):
                await callback_result

    async def _request(self, method: str, url: str, *, auth: bool = True) -> Any:
        """Request JSON, refreshing and retrying once only after an initial 401."""
        rejected_access_token = self._access_token
        try:
            return await self._perform_request(
                method,
                url,
                authenticated=auth,
            )
        except WoltAuthenticationError as err:
            if not auth or err.status != 401:
                raise

        async with self._refresh_lock:
            # Another concurrent request may already have rotated the token while
            # this request was waiting for the lock. Reuse that token rather than
            # submitting the same single-use refresh token twice.
            if self._access_token == rejected_access_token:
                await self._refresh_access_token()
        return await self._perform_request(method, url, authenticated=True)

    async def fetch_orders(self) -> list[dict[str, Any]]:
        """Fetch the account's order page, including recent completed orders."""
        data = await self._request("GET", ACTIVE_ORDERS_URL)
        if not isinstance(data, dict) or not isinstance(data.get("orders"), list):
            raise WoltInvalidPayloadError("Wolt orders payload is invalid")
        return [order for order in data["orders"] if isinstance(order, dict)]

    async def fetch_active_orders(self) -> list[dict[str, Any]]:
        """Fetch only trackable active orders from the account's order page."""
        return [order for order in await self.fetch_orders() if is_active_order(order)]

    async def fetch_order_details(self, purchase_id: str) -> dict[str, Any]:
        """Fetch rich purchase-tracking details for an order."""
        data = await self._request(
            "GET", ORDER_DETAILS_URL.format(quote(purchase_id, safe=""))
        )
        if not isinstance(data, dict):
            raise WoltInvalidPayloadError("Wolt order details payload is invalid")
        details = data.get("order_details")
        if isinstance(details, dict):
            return details
        if isinstance(details, list) and details and isinstance(details[0], dict):
            return details[0]
        raise WoltInvalidPayloadError("Wolt order details payload is invalid")

    async def fetch_venue_details(self, slug: str) -> dict[str, Any]:
        """Fetch public venue details without sending account credentials."""
        data = await self._request(
            "GET",
            VENUE_CONTENT_URL.format(quote(slug, safe="")),
            auth=False,
        )
        if not isinstance(data, dict):
            raise WoltInvalidPayloadError("Wolt venue payload is invalid")
        venue = data.get("venue") or data.get("venue_info")
        if not isinstance(venue, dict):
            raise WoltInvalidPayloadError("Wolt venue payload is invalid")
        return data
