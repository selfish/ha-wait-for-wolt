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
        ("active_orders.json", [{"order_id": "sanitized-order-001"}]),
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


async def test_authenticated_request_refreshes_tokens(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    load_json_fixture: Callable[[str], Any],
) -> None:
    """Refresh credentials before an authenticated order request."""
    aioclient_mock.post(REFRESH_URL, json=load_json_fixture("token_refresh.json"))
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

    assert await api.fetch_active_orders() == [{"order_id": "sanitized-order-001"}]
    assert aioclient_mock.call_count == 2
    refresh_call, orders_call = aioclient_mock.mock_calls
    assert refresh_call[2]["refreshToken"] == "sanitized-refresh-token"
    assert orders_call[3]["authorization"] == "Bearer sanitized-access-token-next"
    assert orders_call[3]["w-wolt-session-id"] == "sanitized-session-id"


async def test_authentication_failure_stops_order_request(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    load_json_fixture: Callable[[str], Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Do not call the order endpoint with stale credentials after refresh fails."""
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
    assert aioclient_mock.call_count == 1
    assert "Token refresh failed" in caplog.text
    assert "sanitized-refresh-token" not in caplog.text


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
