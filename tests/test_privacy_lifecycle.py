"""Regression gates for safe legacy upgrades and per-entry lifecycle."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wait_for_wolt.api import WoltApi, WoltRateLimitError
from custom_components.wait_for_wolt.const import DOMAIN
from custom_components.wait_for_wolt.privacy import location_allowed

DATA = {"bearer_token": "test-access", "refresh_token": "test-refresh", "venue_ids": []}
OID = "a" * 24
ACTIVE = {"purchase_id": OID, "telemetry": {"order_status_type": "IN_PROGRESS"}}


def state(hass, entry, kind, oid=OID):
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{oid}_{kind}"
    )
    return hass.states.get(entity_id) if entity_id else None


@pytest.mark.parametrize(
    "options", [{}, {"tracking_maps": False}, {"tracking_maps": True}]
)
async def test_renamed_duration_never_becomes_status(hass, options):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, options=options)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"wolt_{OID}",
        config_entry=entry,
        suggested_object_id="dinner_countdown",
    )
    with (
        patch.object(WoltApi, "fetch_orders", AsyncMock(return_value=[ACTIVE])),
        patch.object(WoltApi, "fetch_order_details", AsyncMock(return_value={})),
        patch.object(WoltApi, "fetch_venue_location", AsyncMock(return_value={})),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert registry.async_get(old.entity_id).unique_id.endswith("_delivery")
        assert hass.states.get(old.entity_id).attributes["device_class"] == "duration"
        assert state(hass, entry, "status").entity_id != old.entity_id


async def test_disabled_pickup_does_not_authorize_other_or_future_locations(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"wolt_pickup_{OID}",
        config_entry=entry,
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    with (
        patch.object(
            WoltApi, "fetch_orders", AsyncMock(return_value=[ACTIVE])
        ) as orders,
        patch.object(
            WoltApi,
            "fetch_order_details",
            AsyncMock(return_value={"_drivers": [{"location": [30, 20]}]}),
        ),
        patch.object(
            WoltApi, "fetch_venue_location", AsyncMock(return_value={})
        ) as public,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert location_allowed(entry, OID, "pickup")
        assert not location_allowed(entry, OID, "delivery")
        assert "latitude" not in state(hass, entry, "delivery").attributes
        assert (
            registry.async_get(old.entity_id).disabled_by
            is er.RegistryEntryDisabler.USER
        )
        public.assert_not_awaited()
        orders.return_value = [ACTIVE, {**ACTIVE, "purchase_id": "synthetic-two"}]
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()
        assert state(hass, entry, "pickup", "synthetic-two") is None
        assert state(hass, entry, "destination") is None
        assert (
            "latitude" not in state(hass, entry, "delivery", "synthetic-two").attributes
        )
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert not location_allowed(entry, "synthetic-two", "delivery")
        public.assert_not_awaited()


@pytest.mark.parametrize(
    "terminal",
    [
        "DELIVERED",
        "CANCELLED",
        "FAILED",
        None,
        {"private": "do-not-publish"},
        ["do-not-publish"],
    ],
)
async def test_authoritative_terminal_clears_all_entities_and_survives_reload(
    hass, terminal
):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, options={"tracking_maps": True})
    entry.add_to_hass(hass)
    future = (dt_util.utcnow() + timedelta(minutes=2)).isoformat()
    payload = {
        "status": "preparing",
        "delivery_eta": future,
        "telemetry": {"order_status_type": "IN_PROGRESS"},
        "_drivers": [
            {
                "location": [30, 20],
                "name": "do-not-publish",
                "payment": {"card": "do-not-publish"},
            }
        ],
    }
    with (
        patch.object(
            WoltApi, "fetch_orders", AsyncMock(return_value=[ACTIVE])
        ) as orders,
        patch.object(
            WoltApi, "fetch_order_details", AsyncMock(return_value=payload)
        ) as rich,
        patch.object(
            WoltApi,
            "fetch_venue_location",
            AsyncMock(return_value={"latitude": 20, "longitude": 30}),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert state(hass, entry, "delivery").state == "2"
        assert state(hass, entry, "delivery").entity_id.startswith(
            "sensor.wolt_delivery_"
        )
        assert OID not in state(hass, entry, "delivery").attributes["friendly_name"]
        orders.return_value = [
            {
                **ACTIVE,
                "delivery_eta": future,
                "telemetry": {"order_status_type": terminal},
            }
        ]
        rich.reset_mock()
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()
        rich.assert_not_awaited()
        for kind in ("delivery", "eta", "pickup", "destination"):
            s = state(hass, entry, kind)
            assert "latitude" not in s.attributes
            assert "minutes_to_arrival" not in s.attributes
            assert "do-not-publish" not in str(s.attributes)
        assert state(hass, entry, "eta").state == "unknown"
        assert state(hass, entry, "delivery").state == "unknown"
        for kind in ("pickup", "destination"):
            assert state(hass, entry, kind).state == "inactive"
            assert state(hass, entry, kind).attributes["route_point_type"] == kind
            assert (
                state(hass, entry, kind).attributes["coordinate_source"]
                == "unavailable"
            )
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert state(hass, entry, "delivery").state == "unknown"
        assert state(hass, entry, "pickup") is not None
        rich.assert_not_awaited()


async def test_two_entries_cannot_steal_legacy_identity_or_location(hass):
    one = MockConfigEntry(domain=DOMAIN, data=DATA)
    two = MockConfigEntry(domain=DOMAIN, data=DATA)
    one.add_to_hass(hass)
    two.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor", DOMAIN, f"wolt_{OID}", config_entry=one
    )
    with (
        patch.object(WoltApi, "fetch_orders", AsyncMock(return_value=[ACTIVE])),
        patch.object(
            WoltApi,
            "fetch_order_details",
            AsyncMock(return_value={"_drivers": [{"location": [30, 20]}]}),
        ),
    ):
        # Loading a domain schedules all its entries through HA itself.
        assert await hass.config_entries.async_setup(two.entry_id)
        await hass.async_block_till_done()
        assert one.state.value == "loaded"
        assert two.state.value == "loaded"
        assert registry.async_get(old.entity_id).config_entry_id == one.entry_id
        assert state(hass, one, "delivery").attributes["latitude"] == 20
        assert "latitude" not in state(hass, two, "delivery").attributes
        assert (
            state(hass, one, "delivery").entity_id
            != state(hass, two, "delivery").entity_id
        )
        assert await hass.config_entries.async_unload(one.entry_id)
        await two.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()
        assert state(hass, two, "status").state == "pending"


async def test_optional_rate_limit_keeps_summary_and_backs_off(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA)
    entry.add_to_hass(hass)
    with (
        patch.object(
            WoltApi, "fetch_orders", AsyncMock(return_value=[ACTIVE])
        ) as orders,
        patch.object(
            WoltApi,
            "fetch_order_details",
            AsyncMock(side_effect=WoltRateLimitError("limited")),
        ) as rich,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        await entry.runtime_data.coordinator.async_refresh()
        rich.assert_awaited_once()
        assert orders.await_count == 2
        assert state(hass, entry, "status").state == "pending"
        orders.return_value = []
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()
        assert not entry.runtime_data.coordinator._rich_retry
        assert state(hass, entry, "delivery").state == "unavailable"


async def test_destination_never_silently_uses_home(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA, options={"tracking_maps": True})
    entry.add_to_hass(hass)
    hass.states.async_set("zone.home", "0", {"latitude": 12, "longitude": 34})
    with (
        patch.object(WoltApi, "fetch_orders", AsyncMock(return_value=[ACTIVE])),
        patch.object(WoltApi, "fetch_order_details", AsyncMock(return_value={})),
        patch.object(WoltApi, "fetch_venue_location", AsyncMock(return_value={})),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        attrs = state(hass, entry, "destination").attributes
        assert attrs["coordinate_source"] == "unavailable"
        assert "latitude" not in attrs


@pytest.mark.parametrize("returned", [True, False])
async def test_partial_upgrade_collision_preserves_both_delivery_targets(
    hass, returned
):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        "sensor", DOMAIN, f"wolt_{OID}", config_entry=entry
    )
    current = registry.async_get_or_create(
        "sensor", DOMAIN, f"{entry.entry_id}_{OID}_delivery", config_entry=entry
    )
    with (
        patch.object(
            WoltApi,
            "fetch_orders",
            AsyncMock(return_value=[ACTIVE] if returned else []),
        ),
        patch.object(WoltApi, "fetch_order_details", AsyncMock(return_value={})),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert registry.async_get(legacy.entity_id).unique_id == f"wolt_{OID}"
        assert registry.async_get(current.entity_id).unique_id.endswith("_delivery")
        for entity in (legacy, current):
            live = hass.states.get(entity.entity_id)
            assert live is not None
            assert live.attributes["device_class"] == "duration"
            assert "latitude" not in live.attributes
            assert live.state == ("unknown" if returned else "unavailable")
