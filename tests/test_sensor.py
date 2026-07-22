"""Tests for Wolt order and venue sensor behavior."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant

from custom_components.wait_for_wolt.api import WoltApi, WoltConnectionError
from custom_components.wait_for_wolt.const import (
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    CONF_VENUE_IDS,
    DOMAIN,
)
from custom_components.wait_for_wolt.sensor import (
    WoltOrderSensor,
    WoltVenueSensor,
    _setup_sensors,
    async_setup_platform,
)


def load_json_fixture(name: str) -> Any:
    """Load a sanitized fixture."""
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


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


async def test_initial_active_order_is_added_once() -> None:
    """Avoid submitting the same initial order entity twice to Home Assistant."""
    add_entities = Mock()
    cancel_interval = Mock()

    with (
        patch("custom_components.wait_for_wolt.sensor.async_get_clientsession"),
        patch(
            "custom_components.wait_for_wolt.sensor.WoltApi.fetch_active_orders",
            AsyncMock(return_value=[{"purchase_id": "sanitized-purchase-001"}]),
        ),
        patch(
            "custom_components.wait_for_wolt.sensor.async_track_time_interval",
            return_value=cancel_interval,
        ),
    ):
        returned_cancel = await _setup_sensors(
            Mock(),
            add_entities,
            "Sanitized Wolt",
            "sanitized-session-id",
            "sanitized-access-token",
            "sanitized-refresh-token",
        )

    assert returned_cancel is cancel_interval
    assert add_entities.call_count == 1
    entities = add_entities.call_args.args[0]
    assert [entity.order_id for entity in entities] == ["sanitized-purchase-001"]
    assert add_entities.call_args.kwargs == {"update_before_add": True}


async def test_polling_discovers_only_new_orders_after_empty_response() -> None:
    """Discover a later order once and tolerate subsequent empty responses."""
    add_entities = Mock()
    scheduled_update = None

    def capture_interval(_hass: Any, update: Any, _interval: Any) -> Mock:
        nonlocal scheduled_update
        scheduled_update = update
        return Mock()

    with (
        patch("custom_components.wait_for_wolt.sensor.async_get_clientsession"),
        patch(
            "custom_components.wait_for_wolt.sensor.WoltApi.fetch_active_orders",
            AsyncMock(
                side_effect=[
                    [],
                    [{"purchase_id": "sanitized-purchase-001"}],
                    [],
                    [{"purchase_id": "sanitized-purchase-001"}],
                ]
            ),
        ),
        patch(
            "custom_components.wait_for_wolt.sensor.async_track_time_interval",
            side_effect=capture_interval,
        ),
    ):
        await _setup_sensors(
            Mock(),
            add_entities,
            "Sanitized Wolt",
            "sanitized-session-id",
            "sanitized-access-token",
            "sanitized-refresh-token",
        )
        assert scheduled_update is not None
        await scheduled_update()
        await scheduled_update()
        await scheduled_update()

    assert add_entities.call_count == 1
    entities = add_entities.call_args.args[0]
    assert [entity.order_id for entity in entities] == ["sanitized-purchase-001"]


async def test_config_entry_persists_rotated_tokens_via_api_callback() -> None:
    """Keep Home Assistant persistence outside the extracted API layer."""
    hass = Mock()
    entry = Mock(
        data={
            "session_id": "test-session",
            "bearer_token": "old-access-token",
            "refresh_token": "old-refresh-token",
            "preserved": True,
        }
    )
    api = Mock(spec=WoltApi)
    api.fetch_active_orders = AsyncMock(return_value=[])

    with (
        patch("custom_components.wait_for_wolt.sensor.async_get_clientsession"),
        patch(
            "custom_components.wait_for_wolt.sensor.WoltApi", return_value=api
        ) as api_cls,
        patch("custom_components.wait_for_wolt.sensor.async_track_time_interval"),
    ):
        await _setup_sensors(
            hass,
            Mock(),
            "Wolt",
            "test-session",
            "old-access-token",
            "old-refresh-token",
            entry=entry,
        )

    callback = api_cls.call_args.kwargs["token_update_callback"]
    callback("new-access-token", "new-refresh-token")

    hass.config_entries.async_update_entry.assert_called_once_with(
        entry,
        data={
            "session_id": "test-session",
            "bearer_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "preserved": True,
        },
    )


async def test_order_sensor_state_attributes_and_availability() -> None:
    """Expose a sanitized order response and become unavailable on API failure."""
    api = AsyncMock(spec=WoltApi)
    api.fetch_order_details.return_value = load_json_fixture("order_details.json")[
        "order_details"
    ][0]
    sensor = WoltOrderSensor(
        api,
        "sanitized-order-001",
        "Wolt sanitized-order-001",
    )

    await sensor.async_update()

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

    api.fetch_order_details.side_effect = WoltConnectionError("offline")
    await sensor.async_update()

    assert not sensor.available


async def test_order_sensor_normalizes_current_status_object() -> None:
    """Expose the current purchase-tracking status object as a scalar state."""
    api = AsyncMock(spec=WoltApi)
    api.fetch_order_details.return_value = {
        "status": {"value": "In progress"},
        "venue_name": "Sanitized Test Venue",
    }
    sensor = WoltOrderSensor(api, "sanitized-order-001", "Wolt order")

    await sensor.async_update()

    assert sensor.available
    assert sensor.native_value == "In progress"


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
