"""Tests for Wolt order and venue sensor behavior."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
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
    WoltOrderEtaSensor,
    WoltOrderStatusSensor,
    WoltVenueSensor,
    async_setup_entry,
    async_setup_platform,
    extract_order_eta,
    normalize_order_status,
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
    assert [entity.order_id for entity in entities] == [order_id, order_id]
    assert [type(entity) for entity in entities] == [
        WoltOrderStatusSensor,
        WoltOrderEtaSensor,
    ]
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
    assert [entity.order_id for entity in add_entities.call_args.args[0]] == [
        order_id,
        order_id,
    ]


async def test_order_entities_are_typed_scoped_and_privacy_safe() -> None:
    """Expose stable status/ETA entities without item or payment history."""
    order_id = "sanitized-order-001"
    details = load_json_fixture("order_details.json")["order_details"][0]
    coordinator = mock_coordinator(
        WoltCoordinatorData(
            orders={order_id: {"purchase_id": order_id}},
            active_order_ids=frozenset({order_id}),
            details={order_id: details},
        )
    )
    status = WoltOrderStatusSensor(coordinator, "entry-001", order_id)
    eta = WoltOrderEtaSensor(coordinator, "entry-001", order_id)

    assert status.unique_id == "entry-001_sanitized-order-001_status"
    assert eta.unique_id == "entry-001_sanitized-order-001_eta"
    assert status.entity_description.device_class is SensorDeviceClass.ENUM
    assert eta.entity_description.device_class is SensorDeviceClass.TIMESTAMP
    assert status.native_value == "on_the_way"
    assert eta.native_value == datetime(2030, 1, 1, 12, 30, tzinfo=UTC)
    assert status.available
    assert eta.available
    assert status.extra_state_attributes == {}
    assert "Sanitized item" not in json.dumps(status.extra_state_attributes)
    assert "0.00 TEST" not in json.dumps(status.extra_state_attributes)
    assert status.device_info == eta.device_info
    assert order_id not in status.device_info["name"]

    coordinator.last_update_success = False
    assert not status.available
    assert not eta.available


async def test_order_sensor_normalizes_current_status_object() -> None:
    """Normalize the current purchase-tracking status object."""
    order_id = "sanitized-order-001"
    coordinator = mock_coordinator(
        WoltCoordinatorData(
            orders={order_id: {"purchase_id": order_id}},
            active_order_ids=frozenset({order_id}),
            details={order_id: {"status": {"value": "In progress"}}},
        )
    )
    sensor = WoltOrderStatusSensor(coordinator, "entry-001", order_id)

    assert sensor.available
    assert sensor.native_value == "pending"


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
    sensor = WoltOrderStatusSensor(coordinator, "entry-001", order_id)

    assert sensor.available
    assert sensor.native_value == "delivered"


async def test_final_telemetry_overrides_stale_display_status() -> None:
    """Never let stale display text hide an authoritative final state."""
    order_id = "sanitized-order-001"
    coordinator = mock_coordinator(
        WoltCoordinatorData(
            orders={
                order_id: {
                    "purchase_id": order_id,
                    "status": {"value": "In progress"},
                    "telemetry": {"order_status_type": "DELIVERED"},
                }
            },
            active_order_ids=frozenset(),
            details={},
        )
    )

    sensor = WoltOrderStatusSensor(coordinator, "entry-001", order_id)

    assert sensor.native_value == "delivered"


async def test_in_progress_telemetry_rejects_stale_final_display_status() -> None:
    """Keep an authoritative active order active despite stale final display text."""
    order_id = "sanitized-order-001"
    coordinator = mock_coordinator(
        WoltCoordinatorData(
            orders={order_id: {"purchase_id": order_id}},
            active_order_ids=frozenset({order_id}),
            details={
                order_id: {
                    "status": {"value": "Delivered"},
                    "telemetry": {"order_status_type": "IN_PROGRESS"},
                }
            },
        )
    )

    sensor = WoltOrderStatusSensor(coordinator, "entry-001", order_id)

    assert sensor.native_value == "pending"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Preparing your order", "preparing"),
        ("READY_FOR_PICKUP", "ready_for_pickup"),
        ("Courier picked up", "picked_up"),
        ("On the way", "on_the_way"),
        ("Courier nearby", "arriving"),
        ("CANCELLED", "cancelled"),
        ("REJECTED", "failed"),
        ("new private state", "unknown"),
    ],
)
def test_order_status_normalization_is_stable(raw: str, expected: str) -> None:
    """Keep automations stable when Wolt changes display text."""
    assert normalize_order_status({"status": {"value": raw}}) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2030-01-01T12:30:00Z", datetime(2030, 1, 1, 12, 30, tzinfo=UTC)),
        (1893501000000, datetime(2030, 1, 1, 12, 30, tzinfo=UTC)),
        (35, None),
        (0, None),
        (-1, None),
        ({"min": 25, "max": 35}, None),
        (True, None),
        ("25-35 min", None),
        (None, None),
    ],
)
def test_order_eta_requires_an_explicit_timestamp(value: Any, expected: Any) -> None:
    """Never guess a timestamp from Wolt's human-readable duration text."""
    assert extract_order_eta({"delivery_eta": value}) == expected


async def test_legacy_order_unique_id_migrates_to_scoped_status_entity(
    hass: HomeAssistant,
) -> None:
    """Preserve the existing status entity while adding config-entry scope."""
    order_id = "sanitized-purchase-001"
    coordinator = mock_coordinator(
        WoltCoordinatorData(
            orders={order_id: {"purchase_id": order_id}},
            active_order_ids=frozenset({order_id}),
            details={order_id: {"status": "delivery"}},
        )
    )
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_NAME: "Sanitized Wolt"})
    entry.runtime_data = WoltRuntimeData(Mock(spec=WoltApi), coordinator)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"wolt_{order_id}",
        config_entry=entry,
    )

    await async_setup_entry(hass, entry, Mock())

    migrated = registry.async_get(legacy.entity_id)
    assert migrated is not None
    assert migrated.unique_id == f"{entry.entry_id}_{order_id}_status"
    assert migrated.translation_key == "order_status"


async def test_inactive_legacy_order_is_migrated_and_restored(
    hass: HomeAssistant,
) -> None:
    """Restore an existing final order entity after an upgrade and restart."""
    order_id = "sanitized-purchase-001"
    coordinator = mock_coordinator(
        WoltCoordinatorData(
            orders={
                order_id: {
                    "purchase_id": order_id,
                    "status": {"value": "In progress"},
                    "telemetry": {"order_status_type": "DELIVERED"},
                }
            },
            active_order_ids=frozenset(),
            details={},
        )
    )
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_NAME: "Sanitized Wolt"})
    entry.runtime_data = WoltRuntimeData(Mock(spec=WoltApi), coordinator)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"wolt_{order_id}",
        config_entry=entry,
    )
    add_entities = Mock()

    await async_setup_entry(hass, entry, add_entities)

    migrated = registry.async_get(legacy.entity_id)
    assert migrated is not None
    assert migrated.unique_id == f"{entry.entry_id}_{order_id}_status"
    entities = add_entities.call_args.args[0]
    assert len(entities) == 2
    status = next(
        entity for entity in entities if isinstance(entity, WoltOrderStatusSensor)
    )
    assert status.available
    assert status.native_value == "delivered"


async def test_inactive_scoped_order_is_restored_after_restart(
    hass: HomeAssistant,
) -> None:
    """Recreate an existing scoped entity when its order is already final."""
    order_id = "sanitized-purchase-001"
    coordinator = mock_coordinator(
        WoltCoordinatorData(
            orders={
                order_id: {
                    "purchase_id": order_id,
                    "telemetry": {"order_status_type": "DELIVERED"},
                }
            },
            active_order_ids=frozenset(),
            details={},
        )
    )
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_NAME: "Sanitized Wolt"})
    entry.runtime_data = WoltRuntimeData(Mock(spec=WoltApi), coordinator)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_{order_id}_status",
        config_entry=entry,
    )
    add_entities = Mock()

    await async_setup_entry(hass, entry, add_entities)

    entities = add_entities.call_args.args[0]
    assert len(entities) == 2
    status = next(
        entity for entity in entities if isinstance(entity, WoltOrderStatusSensor)
    )
    assert status.native_value == "delivered"


async def test_legacy_entity_is_not_migrated_across_config_entries(
    hass: HomeAssistant,
) -> None:
    """Never steal another account's legacy registry entity on an ID collision."""
    order_id = "sanitized-purchase-001"
    first_entry = MockConfigEntry(domain=DOMAIN, data={CONF_NAME: "First Wolt"})
    first_entry.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"wolt_{order_id}",
        config_entry=first_entry,
    )
    coordinator = mock_coordinator(
        WoltCoordinatorData(
            orders={order_id: {"purchase_id": order_id}},
            active_order_ids=frozenset({order_id}),
            details={},
        )
    )
    second_entry = MockConfigEntry(domain=DOMAIN, data={CONF_NAME: "Second Wolt"})
    second_entry.runtime_data = WoltRuntimeData(Mock(spec=WoltApi), coordinator)
    second_entry.add_to_hass(hass)

    await async_setup_entry(hass, second_entry, Mock())

    unchanged = registry.async_get(legacy.entity_id)
    assert unchanged is not None
    assert unchanged.config_entry_id == first_entry.entry_id
    assert unchanged.unique_id == f"wolt_{order_id}"


def test_order_unique_ids_are_scoped_to_the_config_entry() -> None:
    """Avoid collisions when two Wolt accounts expose different purchases."""
    order_id = "sanitized-purchase-001"
    coordinator = mock_coordinator(
        WoltCoordinatorData(
            orders={order_id: {}},
            active_order_ids=frozenset({order_id}),
            details={},
        )
    )

    first = WoltOrderStatusSensor(coordinator, "entry-a", order_id)
    second = WoltOrderStatusSensor(coordinator, "entry-b", order_id)

    assert first.unique_id != second.unique_id


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
