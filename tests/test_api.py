"""Synthetic offline tests for the Home Assistant-independent Wolt API client."""

import asyncio
from collections import deque
from typing import Any

import aiohttp
import pytest

from custom_components.wait_for_wolt.api import (
    WoltApi,
    WoltAuthenticationError,
    WoltConnectionError,
    WoltInvalidPayloadError,
    WoltRateLimitError,
)
from custom_components.wait_for_wolt.const import (
    ACTIVE_ORDERS_URL,
    ORDER_DETAILS_URL,
    REFRESH_URL,
    VENUE_CONTENT_URL,
)


class FakeResponse:
    """Minimal asynchronous response implementing the API client's contract."""

    def __init__(self, status: int, payload: Any = None) -> None:
        self.status = status
        self._payload = payload

    async def json(self) -> Any:
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


class FakeRequestContext:
    """Minimal aiohttp request context manager."""

    def __init__(self, response: FakeResponse | BaseException) -> None:
        self._response = response

    async def __aenter__(self) -> FakeResponse:
        if isinstance(self._response, BaseException):
            raise self._response
        return self._response

    async def __aexit__(self, *_args: Any) -> None:
        return None


class FakeSession:
    """Queue deterministic responses and record requests without network access."""

    def __init__(self, *responses: FakeResponse | BaseException) -> None:
        self._responses = deque(responses)
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        data: dict[str, str] | None = None,
    ) -> FakeRequestContext:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "data": data,
            }
        )
        return FakeRequestContext(self._responses.popleft())

    def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        data: dict[str, str],
    ) -> FakeRequestContext:
        return self.request("POST", url, headers=headers, data=data)


def make_api(session: FakeSession, session_id: str | None = "test-session") -> WoltApi:
    """Create an API client containing only synthetic credentials."""
    return WoltApi(
        session,  # type: ignore[arg-type]
        session_id,
        "test-access-token",
        "test-refresh-token",
    )


async def test_active_orders_success_uses_current_token_first() -> None:
    """Use a valid access token without refreshing it preemptively."""
    payload = {
        "orders": [
            {
                "purchase_id": "purchase-001",
                "telemetry": {"order_status_type": "IN_PROGRESS"},
            }
        ]
    }
    session = FakeSession(FakeResponse(200, payload))

    assert await make_api(session).fetch_active_orders() == payload["orders"]
    assert len(session.calls) == 1
    assert session.calls[0]["url"] == ACTIVE_ORDERS_URL
    assert session.calls[0]["headers"]["authorization"] == ("Bearer test-access-token")
    assert session.calls[0]["headers"]["w-wolt-session-id"] == "test-session"


@pytest.mark.parametrize(
    "status_type",
    ["DELIVERED", "COMPLETED", "PENDING", "UNKNOWN", ""],
)
async def test_active_orders_rejects_every_non_active_telemetry_state(
    status_type: str,
) -> None:
    """Treat telemetry as authoritative even when legacy hints look active."""
    active = {
        "purchase_id": "purchase-active",
        "telemetry": {"order_status_type": "IN_PROGRESS"},
    }
    not_active = {
        "purchase_id": "purchase-not-active",
        "telemetry": {"order_status_type": status_type},
        "call_to_action": {"type": "ORDER_TRACKING"},
        "status": {"value": "Preparing"},
    }
    session = FakeSession(FakeResponse(200, {"orders": [active, not_active]}))

    assert await make_api(session).fetch_active_orders() == [active]


async def test_active_orders_keeps_legacy_tracking_fallback_without_telemetry() -> None:
    """Keep compatibility with older order items that omit telemetry entirely."""
    legacy_active = {
        "order_id": "legacy-order-active",
        "call_to_action": {"type": "ORDER_TRACKING"},
    }
    session = FakeSession(FakeResponse(200, {"orders": [legacy_active]}))

    assert await make_api(session).fetch_active_orders() == [legacy_active]


@pytest.mark.parametrize(
    "telemetry",
    [{}, None, [], {"order_status_type": None}],
)
async def test_active_orders_rejects_present_incomplete_telemetry(
    telemetry: Any,
) -> None:
    """Never let a malformed present telemetry object reach legacy heuristics."""
    not_active = {
        "purchase_id": "purchase-not-active",
        "telemetry": telemetry,
        "call_to_action": {"type": "ORDER_TRACKING"},
        "status": {"value": "Preparing"},
    }
    session = FakeSession(FakeResponse(200, {"orders": [not_active]}))

    assert await make_api(session).fetch_active_orders() == []


@pytest.mark.parametrize("status_type", ["IN_PROGRESS", "COMPLETED", None])
async def test_active_orders_treats_legacy_top_level_status_as_authoritative(
    status_type: str | None,
) -> None:
    """Apply the same strict contract to the older top-level status field."""
    order = {
        "order_id": "legacy-order",
        "order_status_type": status_type,
        "call_to_action": {"type": "ORDER_TRACKING"},
    }
    session = FakeSession(FakeResponse(200, {"orders": [order]}))

    expected = [order] if status_type == "IN_PROGRESS" else []
    assert await make_api(session).fetch_active_orders() == expected


@pytest.mark.parametrize(
    ("method_name", "payload", "args"),
    [
        ("fetch_active_orders", {"orders": {"unexpected": "shape"}}, ()),
        (
            "fetch_order_details",
            {"order_details": "unexpected-shape"},
            ("purchase-001",),
        ),
        ("fetch_venue_details", {"venue": ["unexpected-shape"]}, ("venue",)),
    ],
)
async def test_malformed_payloads_raise_typed_exception(
    method_name: str,
    payload: dict[str, Any],
    args: tuple[str, ...],
) -> None:
    """Report incompatible endpoint payloads instead of silently accepting them."""
    api = make_api(FakeSession(FakeResponse(200, payload)))

    with pytest.raises(WoltInvalidPayloadError):
        await getattr(api, method_name)(*args)


async def test_malformed_json_raises_typed_payload_exception() -> None:
    """Translate JSON decoding failures from an otherwise successful response."""
    api = make_api(FakeSession(FakeResponse(200, ValueError("malformed JSON"))))

    with pytest.raises(WoltInvalidPayloadError):
        await api.fetch_active_orders()


async def test_unauthorized_request_refreshes_persists_and_retries_once() -> None:
    """Refresh only after 401, expose rotation, notify persistence, and retry once."""
    rotated = ("next-access-token", "next-refresh-token")
    session = FakeSession(
        FakeResponse(401),
        FakeResponse(
            200,
            {"access_token": rotated[0], "refresh_token": rotated[1]},
        ),
        FakeResponse(
            200,
            {
                "orders": [
                    {
                        "purchase_id": "purchase-001",
                        "telemetry": {"order_status_type": "IN_PROGRESS"},
                    }
                ]
            },
        ),
    )
    persisted: list[tuple[str, str]] = []

    async def persist_tokens(access_token: str, refresh_token: str) -> None:
        persisted.append((access_token, refresh_token))

    api = WoltApi(
        session,  # type: ignore[arg-type]
        "test-session",
        "test-access-token",
        "test-refresh-token",
        token_update_callback=persist_tokens,
    )

    assert await api.fetch_active_orders() == [
        {
            "purchase_id": "purchase-001",
            "telemetry": {"order_status_type": "IN_PROGRESS"},
        }
    ]
    assert [call["url"] for call in session.calls] == [
        ACTIVE_ORDERS_URL,
        REFRESH_URL,
        ACTIVE_ORDERS_URL,
    ]
    assert session.calls[1]["method"] == "POST"
    assert session.calls[1]["data"] == {
        "grant_type": "refresh_token",
        "refresh_token": "test-refresh-token",
    }
    assert session.calls[2]["headers"]["authorization"] == ("Bearer next-access-token")
    assert api.access_token == rotated[0]
    assert api.refresh_token == rotated[1]
    assert persisted == [rotated]


async def test_concurrent_unauthorized_requests_share_one_token_refresh() -> None:
    """Serialize concurrent 401 recovery when refresh tokens rotate once."""
    api = make_api(FakeSession())
    both_initial_requests_started = asyncio.Event()
    initial_requests = 0
    refreshes = 0

    async def perform_request(
        _method: str,
        url: str,
        *,
        authenticated: bool,
        data: dict[str, str] | None = None,
    ) -> Any:
        nonlocal initial_requests
        del data
        if (
            url == ACTIVE_ORDERS_URL
            and authenticated
            and api.access_token == "test-access-token"
        ):
            initial_requests += 1
            if initial_requests == 2:
                both_initial_requests_started.set()
            await both_initial_requests_started.wait()
            raise WoltAuthenticationError("expired", status=401)
        return {"orders": []}

    async def refresh_access_token() -> None:
        nonlocal refreshes
        refreshes += 1
        api._access_token = "next-access-token"

    api._perform_request = perform_request  # type: ignore[method-assign]
    api._refresh_access_token = refresh_access_token  # type: ignore[method-assign]

    first, second = await asyncio.gather(
        api.fetch_active_orders(), api.fetch_active_orders()
    )

    assert first == second == []
    assert initial_requests == 2
    assert refreshes == 1


@pytest.mark.parametrize("failed_status", [400, 401, 403])
async def test_authentication_failure_raises_without_looping(
    failed_status: int,
) -> None:
    """Surface refresh rejection as typed authentication failure."""
    session = FakeSession(
        FakeResponse(401), FakeResponse(failed_status, {"error": "no"})
    )

    with pytest.raises(WoltAuthenticationError):
        await make_api(session).fetch_active_orders()

    assert len(session.calls) == 2


async def test_second_unauthorized_response_raises_without_refresh_loop() -> None:
    """Retry the authenticated endpoint only once after successful refresh."""
    session = FakeSession(
        FakeResponse(401),
        FakeResponse(200, {"access_token": "next-access-token"}),
        FakeResponse(401),
    )

    with pytest.raises(WoltAuthenticationError):
        await make_api(session).fetch_active_orders()

    assert len(session.calls) == 3


@pytest.mark.parametrize("session_id", [None, ""])
async def test_authenticated_request_omits_optional_session_header(
    session_id: str | None,
) -> None:
    """Allow accounts without Wolt's optional analytics session identifier."""
    session = FakeSession(FakeResponse(200, {"orders": []}))

    assert await make_api(session, session_id).fetch_active_orders() == []
    assert "w-wolt-session-id" not in session.calls[0]["headers"]


async def test_public_venue_request_sends_no_account_headers() -> None:
    """Never leak account credentials to the public venue endpoint."""
    session = FakeSession(FakeResponse(200, {"venue": {"online": True}}))

    result = await make_api(session).fetch_venue_details("test-venue")

    assert result == {"venue": {"online": True}}
    assert session.calls[0]["url"] == VENUE_CONTENT_URL.format("test-venue")
    assert "authorization" not in session.calls[0]["headers"]
    assert "w-wolt-session-id" not in session.calls[0]["headers"]


async def test_order_details_uses_rich_purchase_tracking_endpoint() -> None:
    """Fetch rich tracking details by purchase ID from restaurant-api."""
    session = FakeSession(FakeResponse(200, {"order_details": {"status": "delivery"}}))

    assert await make_api(session).fetch_order_details("purchase-001") == {
        "status": "delivery"
    }
    assert session.calls[0]["url"] == ORDER_DETAILS_URL.format("purchase-001")
    assert session.calls[0]["url"] == (
        "https://restaurant-api.wolt.com/v2/order_details/purchase_tracking"
        "?purchase_id=purchase-001"
    )


async def test_order_details_accepts_legacy_list_shape() -> None:
    """Keep compatibility with the earlier sanitized tracking fixture shape."""
    session = FakeSession(
        FakeResponse(200, {"order_details": [{"status": "delivery"}]})
    )

    assert await make_api(session).fetch_order_details("purchase-001") == {
        "status": "delivery"
    }


@pytest.mark.parametrize(
    ("response", "exception_type"),
    [
        (TimeoutError(), WoltConnectionError),
        (aiohttp.ClientConnectionError(), WoltConnectionError),
        (FakeResponse(429), WoltRateLimitError),
    ],
)
async def test_transport_and_rate_limit_failures_are_typed(
    response: FakeResponse | BaseException,
    exception_type: type[Exception],
) -> None:
    """Distinguish retryable connectivity and rate-limit failures."""
    with pytest.raises(exception_type):
        await make_api(FakeSession(response)).fetch_active_orders()
