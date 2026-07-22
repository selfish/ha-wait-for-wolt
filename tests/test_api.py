"""Tests for Wolt API request and payload handling."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.wait_for_wolt.const import (
    ACTIVE_ORDERS_URL,
    REFRESH_URL,
    VENUE_CONTENT_URL,
)
from custom_components.wait_for_wolt.sensor import WoltApi


@pytest.fixture
def api() -> WoltApi:
    """Return an API client containing only sanitized credentials."""
    return WoltApi(
        AsyncMock(spec=aiohttp.ClientSession),
        "sanitized-session-id",
        "sanitized-access-token",
        "sanitized-refresh-token",
    )


@pytest.fixture
def load_json_fixture() -> Callable[[str], Any]:
    """Load a sanitized Wolt response fixture."""

    def _load(name: str) -> Any:
        return json.loads((Path(__file__).parent / "fixtures" / name).read_text())

    return _load


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [
        (
            "active_orders.json",
            [
                {
                    "purchase_id": "sanitized-purchase-001",
                    "status": {"value": "In progress"},
                    "telemetry": {"order_status_type": "IN_PROGRESS"},
                    "call_to_action": {"link": "ORDER_TRACKING"},
                    "venue": {"name": "Sanitized Test Venue"},
                }
            ],
        ),
        ("empty_orders.json", []),
        ("malformed_orders.json", []),
    ],
)
async def test_active_order_payload_contract(
    api: WoltApi,
    load_json_fixture: Callable[[str], Any],
    fixture_name: str,
    expected: list[dict[str, str]],
) -> None:
    """Accept order lists and reject incompatible response shapes safely."""
    api._request = AsyncMock(return_value=load_json_fixture(fixture_name))

    assert await api.fetch_active_orders() == expected


async def test_detail_payload_contracts(
    api: WoltApi,
    load_json_fixture: Callable[[str], Any],
) -> None:
    """Reject malformed order and venue payloads without raising."""
    api._request = AsyncMock(
        return_value=load_json_fixture("malformed_order_details.json")
    )
    assert await api.fetch_order_details("sanitized-order-001") is None

    api._request = AsyncMock(return_value=load_json_fixture("malformed_venue.json"))
    assert await api.fetch_venue_details("sanitized-venue") is None


async def test_authenticated_request_uses_current_access_token_without_refresh(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    load_json_fixture: Callable[[str], Any],
) -> None:
    """Avoid rotating a valid Wolt access token before every request."""
    aioclient_mock.get(
        ACTIVE_ORDERS_URL,
        json=load_json_fixture("active_orders.json"),
    )
    api = WoltApi(
        async_get_clientsession(hass),
        "sanitized-session-id",
        "sanitized-access-token",
        "sanitized-refresh-token",
    )

    orders = await api.fetch_active_orders()

    assert orders[0]["purchase_id"] == "sanitized-purchase-001"
    assert aioclient_mock.call_count == 1
    orders_call = aioclient_mock.mock_calls[0]
    assert orders_call[3]["authorization"] == "Bearer sanitized-access-token"
    assert orders_call[3]["w-wolt-session-id"] == "sanitized-session-id"


async def test_unauthorized_request_refreshes_persists_and_retries_once(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    load_json_fixture: Callable[[str], Any],
) -> None:
    """Use Wolt's current refresh flow and persist rotated credentials."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.wait_for_wolt.const import DOMAIN

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "session_id": "sanitized-session-id",
            "bearer_token": "sanitized-access-token",
            "refresh_token": "sanitized-refresh-token",
        },
    )
    entry.add_to_hass(hass)
    orders_response = aioclient_mock.request("get", ACTIVE_ORDERS_URL, status=401)

    async def refresh_then_allow_retry(_method: Any, _url: Any, _data: Any) -> Any:
        orders_response.status = 200
        orders_response._response = json.dumps(
            load_json_fixture("active_orders.json")
        ).encode()
        return refresh_response

    refresh_response = aioclient_mock.request(
        "post",
        REFRESH_URL,
        json=load_json_fixture("token_refresh.json"),
        side_effect=refresh_then_allow_retry,
    )
    api = WoltApi(
        async_get_clientsession(hass),
        "sanitized-session-id",
        "sanitized-access-token",
        "sanitized-refresh-token",
        hass=hass,
        entry=entry,
    )

    orders = await api.fetch_active_orders()

    assert orders[0]["purchase_id"] == "sanitized-purchase-001"
    assert aioclient_mock.call_count == 3
    first_order_call, refresh_call, retry_call = aioclient_mock.mock_calls
    assert first_order_call[3]["authorization"] == "Bearer sanitized-access-token"
    assert refresh_call[2] == {
        "grant_type": "refresh_token",
        "refresh_token": "sanitized-refresh-token",
    }
    assert retry_call[3]["authorization"] == "Bearer sanitized-access-token-next"
    assert entry.data["bearer_token"] == "sanitized-access-token-next"
    assert entry.data["refresh_token"] == "sanitized-refresh-token-next"


async def test_authentication_failure_stops_order_request(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    load_json_fixture: Callable[[str], Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retry authentication once, then stop instead of looping with stale credentials."""
    aioclient_mock.get(ACTIVE_ORDERS_URL, status=401)
    aioclient_mock.post(
        REFRESH_URL,
        status=401,
        json=load_json_fixture("auth_failure.json"),
    )
    api = WoltApi(
        async_get_clientsession(hass),
        "sanitized-session-id",
        "sanitized-access-token",
        "sanitized-refresh-token",
    )

    assert await api.fetch_active_orders() == []
    assert aioclient_mock.call_count == 2
    assert "Token refresh failed" in caplog.text
    assert "sanitized-refresh-token" not in caplog.text


async def test_authenticated_request_omits_missing_session_header(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    load_json_fixture: Callable[[str], Any],
) -> None:
    """Support Wolt accounts that do not expose the analytics session cookie."""
    aioclient_mock.get(
        ACTIVE_ORDERS_URL,
        json=load_json_fixture("active_orders.json"),
    )
    api = WoltApi(
        async_get_clientsession(hass),
        "",
        "sanitized-access-token",
        "sanitized-refresh-token",
    )

    assert await api.fetch_active_orders()
    headers = aioclient_mock.mock_calls[0][3]
    assert "w-wolt-session-id" not in headers


async def test_public_venue_request_sends_no_account_headers(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    load_json_fixture: Callable[[str], Any],
) -> None:
    """Keep account credentials off the public venue endpoint."""
    url = VENUE_CONTENT_URL.format("sanitized-venue")
    aioclient_mock.get(url, json=load_json_fixture("venue_open.json"))
    api = WoltApi(
        async_get_clientsession(hass),
        "sanitized-session-id",
        "sanitized-access-token",
        "sanitized-refresh-token",
    )

    assert await api.fetch_venue_details("sanitized-venue") is not None
    assert aioclient_mock.call_count == 1
    headers = aioclient_mock.mock_calls[0][3]
    assert "authorization" not in headers
    assert "w-wolt-session-id" not in headers
