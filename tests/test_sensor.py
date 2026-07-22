"""Tests for Wolt order and venue sensor behavior."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wait_for_wolt.api import WoltApi, WoltConnectionError
from custom_components.wait_for_wolt.const import (
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    CONF_VENUE_IDS,
    DOMAIN,
)
from custom_components.wait_for_wolt.coordinator import (
    WoltCoordinatorData,
    WoltDataUpdateCoordinator,
    WoltRuntimeData,
)
from custom_components.wait_for_wolt.sensor import (
    WoltOrderSensor,
    WoltVenueSensor,
    async_setup_entry,
    async_setup_platform,
)


def load_json_fixture(name: str) -> Any:
    """Load a sanitized fixture."""
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def mock_coordinator(data: WoltCoordinatorData) -> Mock:
    """Create the coordinator surface consumed by entities and setup."""
    coordinator = Mock(spec=WoltDataUpdateCoordinator)
    coordinator.data = data
    coordinator.last_update_success = True
    coordinator.async_add_listener.return_value = Mock()
    return coordinator


async def test_legacy_yaml_platform_starts_config_entry_import(
    hass: HomeAssistant,
) -> None:
    """Migrate YAML credentials instead of running with non-durable rotation."""
    config = {
        CONF_NAME: "Sanitized Wolt",
        CONF_SESSION_ID: "sanitized-session-id",
        CONF_BEARER_TOKEN: "sanitized-access-token",
        CONF_REFRESH_TOKEN: "sanitized-refresh-token",
        CONF_VENUE_IDS: ["sanitized-venue"],
    }

    with patch.object(
        hass.config_entries.flow,
        "async_init",
        AsyncMock(return_value={}),
    ) as import_flow:
        await async_setup_platform(hass, config, Mock())

    import_flow.assert_awaited_once_with(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data=config,
    )


async def test_initial_active_order_is_added_once(hass: HomeAssistant) -> None:
    """Add the first coordinator order once and register dynamic discovery."""
    order_id = "sanitized-purchase-001"
    coordinator = mock_coordinator(
        WoltCoordinatorData(
            orders={order_id: {"purchase_id": order_id}},
            active_order_ids=frozenset({order_id}),
            details={order_id: {"status": "delivery"}},
        )
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NAME: "Sanitized Wolt", CONF_VENUE_IDS: []},
    )
    entry.runtime_data = WoltRuntimeData(Mock(spec=WoltApi), coordinator)
    entry.add_to_hass(hass)
    add_entities = Mock()

    await async_setup_entry(hass, entry, add_entities)
    listener = coordinator.async_add_listener.call_args.args[0]
    listener()

    assert add_entities.call_count == 1
    entities = add_entities.call_args.args[0]
    assert [entity.order_id for entity in entities] == [order_id]
    assert add_entities.call_args.kwargs == {}


async def test_coordinator_listener_discovers_only_new_orders(
    hass: HomeAssistant,
) -> None:
    """Add an order discovered by a later shared refresh exactly once."""
    coordinator = mock_coordinator(WoltCoordinatorData({}, frozenset(), {}))
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_NAME: "Sanitized Wolt"})
    entry.runtime_data = WoltRuntimeData(Mock(spec=WoltApi), coordinator)
    entry.add_to_hass(hass)
    add_entities = Mock()

    await async_setup_entry(hass, entry, add_entities)
    listener = coordinator.async_add_listener.call_args.args[0]
    order_id = "sanitized-purchase-001"
    coordinator.data = WoltCoordinatorData(
        orders={order_id: {"purchase_id": order_id}},
        active_order_ids=frozenset({order_id}),
        details={order_id: {"status": "delivery"}},
    )
    listener()
    listener()

    assert add_entities.call_count == 1
    assert [entity.order_id for entity in add_entities.call_args.args[0]] == [order_id]


async def test_order_sensor_state_attributes_and_availability() -> None:
    """Expose one sanitized order from the coordinator's coherent snapshot."""
    order_id = "sanitized-order-001"
    details = load_json_fixture("order_details.json")["order_details"][0]
    coordinator = mock_coordinator(
        WoltCoordinatorData(
            orders={order_id: {"purchase_id": order_id}},
            active_order_ids=frozenset({order_id}),
            details={order_id: details},
        )
    )
    sensor = WoltOrderSensor(
        coordinator,
        order_id,
        "Wolt sanitized-order-001",
    )

    assert sensor.unique_id == "wolt_sanitized-order-001"
    assert sensor.native_value == "delivery"
    assert sensor.available
    assert sensor.extra_state_attributes == {
        "delivery_eta": "2030-01-01T12:30:00Z",
        "client_pre_estimate": "25-35 min",
        "venue_name": "Sanitized Test Venue",
        "payment_amount": "0.00 TEST",
        "items": ["Sanitized item"],
    }

    coordinator.last_update_success = False
    assert not sensor.available


async def test_order_sensor_normalizes_current_status_object() -> None:
    """Expose the current purchase-tracking status object as a scalar state."""
    order_id = "sanitized-order-001"
    coordinator = mock_coordinator(
        WoltCoordinatorData(
            orders={order_id: {"purchase_id": order_id}},
            active_order_ids=frozenset({order_id}),
            details={order_id: {"status": {"value": "In progress"}}},
        )
    )
    sensor = WoltOrderSensor(coordinator, order_id, "Wolt order")

    assert sensor.available
    assert sensor.native_value == "In progress"


async def test_order_sensor_keeps_final_status_from_order_summary() -> None:
    """Expose a delivered transition after rich active tracking stops."""
    order_id = "sanitized-order-001"
    coordinator = mock_coordinator(
        WoltCoordinatorData(
            orders={
                order_id: {
                    "purchase_id": order_id,
                    "status": {"value": "Delivered"},
                    "telemetry": {"order_status_type": "DELIVERED"},
                }
            },
            active_order_ids=frozenset(),
            details={},
        )
    )
    sensor = WoltOrderSensor(coordinator, order_id, "Wolt order")

    assert sensor.available
    assert sensor.native_value == "Delivered"


@pytest.mark.parametrize(
    ("fixture_name", "expected_state"),
    [("venue_open.json", "open"), ("venue_closed.json", "closed")],
)
async def test_venue_sensor_state_and_availability(
    fixture_name: str,
    expected_state: str,
) -> None:
    """Handle open and explicitly closed venues without assuming metadata exists."""
    api = AsyncMock(spec=WoltApi)
    api.fetch_venue_details.return_value = load_json_fixture(fixture_name)
    sensor = WoltVenueSensor(api, "sanitized-venue", "Wolt sanitized-venue")

    await sensor.async_update()

    assert sensor.unique_id == "wolt_venue_sanitized-venue"
    assert sensor.native_value == expected_state
    assert sensor.available

    api.fetch_venue_details.side_effect = WoltConnectionError("offline")
    await sensor.async_update()

    assert not sensor.available


async def test_venue_sensor_respects_explicit_closed_status() -> None:
    """Prefer an explicit closed status over broader online metadata."""
    api = AsyncMock(spec=WoltApi)
    api.fetch_venue_details.return_value = {
        "venue": {
            "online": True,
            "delivery_open_status": {"is_open": False},
        }
    }
    sensor = WoltVenueSensor(api, "sanitized-venue", "Wolt sanitized-venue")

    await sensor.async_update()

    assert sensor.available
    assert sensor.native_value == "closed"
