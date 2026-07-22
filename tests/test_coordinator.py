"""Tests for shared Wolt polling and Home Assistant error semantics."""

from datetime import timedelta
from unittest.mock import AsyncMock, call

import pytest
from homeassistant.config_entries import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wait_for_wolt.api import (
    WoltApi,
    WoltAuthenticationError,
    WoltConnectionError,
    WoltInvalidPayloadError,
    WoltRateLimitError,
)
from custom_components.wait_for_wolt.const import DOMAIN
from custom_components.wait_for_wolt.coordinator import (
    ACTIVE_UPDATE_INTERVAL,
    IDLE_UPDATE_INTERVAL,
    WoltDataUpdateCoordinator,
)


def make_coordinator(
    hass: HomeAssistant,
    api: AsyncMock,
) -> WoltDataUpdateCoordinator:
    """Create a coordinator with a synthetic config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    return WoltDataUpdateCoordinator(hass, entry, api)


async def test_coordinator_fetches_one_shared_active_order_snapshot(
    hass: HomeAssistant,
) -> None:
    """Fetch the order page once and details once per active order."""
    active = {
        "purchase_id": "purchase-active",
        "status": {"value": "In progress"},
        "telemetry": {"order_status_type": "IN_PROGRESS"},
    }
    second_active = {
        "purchase_id": "purchase-second",
        "status": {"value": "Preparing"},
        "telemetry": {"order_status_type": "IN_PROGRESS"},
    }
    completed = {
        "purchase_id": "purchase-complete",
        "status": {"value": "Delivered"},
        "telemetry": {"order_status_type": "DELIVERED"},
    }
    api = AsyncMock(spec=WoltApi)
    api.fetch_orders.return_value = [active, completed, second_active]
    api.fetch_order_details.return_value = {"status": {"value": "On the way"}}
    coordinator = make_coordinator(hass, api)

    data = await coordinator._async_update_data()

    assert data.orders == {
        "purchase-active": active,
        "purchase-complete": completed,
        "purchase-second": second_active,
    }
    assert data.active_order_ids == frozenset({"purchase-active", "purchase-second"})
    assert data.details == {
        "purchase-active": {"status": {"value": "On the way"}},
        "purchase-second": {"status": {"value": "On the way"}},
    }
    assert coordinator.update_interval == ACTIVE_UPDATE_INTERVAL
    api.fetch_orders.assert_awaited_once_with()
    assert api.fetch_order_details.await_args_list == [
        call("purchase-active"),
        call("purchase-second"),
    ]


async def test_coordinator_uses_conservative_idle_interval(
    hass: HomeAssistant,
) -> None:
    """Avoid rich tracking requests and poll slowly when no order is active."""
    api = AsyncMock(spec=WoltApi)
    api.fetch_orders.return_value = []
    coordinator = make_coordinator(hass, api)

    data = await coordinator._async_update_data()

    assert data.orders == {}
    assert data.active_order_ids == frozenset()
    assert data.details == {}
    assert coordinator.update_interval == IDLE_UPDATE_INTERVAL
    api.fetch_order_details.assert_not_awaited()


@pytest.mark.parametrize(
    "error",
    [WoltConnectionError("not ready", status=404), WoltInvalidPayloadError("changed")],
)
async def test_optional_tracking_failure_keeps_order_summary_available(
    hass: HomeAssistant,
    error: Exception,
) -> None:
    """Degrade to the orders page when optional rich tracking is unavailable."""
    active = {
        "purchase_id": "purchase-active",
        "status": {"value": "In progress"},
        "telemetry": {"order_status_type": "IN_PROGRESS"},
    }
    api = AsyncMock(spec=WoltApi)
    api.fetch_orders.return_value = [active]
    api.fetch_order_details.side_effect = error

    data = await make_coordinator(hass, api)._async_update_data()

    assert data.orders == {"purchase-active": active}
    assert data.active_order_ids == frozenset({"purchase-active"})
    assert data.details == {}


async def test_optional_tracking_warning_is_not_repeated_each_active_poll(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Avoid a warning every 30 seconds during a rich-endpoint outage."""
    active = {
        "purchase_id": "purchase-active",
        "telemetry": {"order_status_type": "IN_PROGRESS"},
    }
    api = AsyncMock(spec=WoltApi)
    api.fetch_orders.return_value = [active]
    api.fetch_order_details.side_effect = WoltInvalidPayloadError("changed")
    coordinator = make_coordinator(hass, api)

    await coordinator._async_update_data()
    await coordinator._async_update_data()

    assert (
        caplog.messages.count("Rich Wolt order tracking details are unavailable") == 1
    )


@pytest.mark.parametrize(
    "error",
    [
        WoltConnectionError("offline"),
        WoltRateLimitError("limited", status=429),
        WoltInvalidPayloadError("invalid"),
    ],
)
async def test_coordinator_translates_update_failures(
    hass: HomeAssistant,
    error: Exception,
) -> None:
    """Expose transient and contract failures as coordinator update failures."""
    api = AsyncMock(spec=WoltApi)
    api.fetch_orders.side_effect = error

    with pytest.raises(UpdateFailed):
        await make_coordinator(hass, api)._async_update_data()


async def test_coordinator_translates_auth_failure_to_reauthentication(
    hass: HomeAssistant,
) -> None:
    """Start Home Assistant's reauthentication path for rejected credentials."""
    api = AsyncMock(spec=WoltApi)
    api.fetch_orders.side_effect = WoltAuthenticationError("rejected", status=401)

    with pytest.raises(ConfigEntryAuthFailed):
        await make_coordinator(hass, api)._async_update_data()


def test_poll_intervals_are_intentionally_conservative() -> None:
    """Document the active and idle request-volume policy."""
    assert timedelta(seconds=30) == ACTIVE_UPDATE_INTERVAL
    assert timedelta(minutes=5) == IDLE_UPDATE_INTERVAL
