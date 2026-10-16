"""Venue labels distinguish simultaneous purchases without changing identities."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wait_for_wolt.api import WoltApi
from custom_components.wait_for_wolt.const import DOMAIN
from custom_components.wait_for_wolt.facts import venue_name


@pytest.mark.parametrize("value", [None, "", "  ", True, 123, [], {}, "bad\nname"])
def test_invalid_venue_name(value):
    assert venue_name({"venue": {"name": value}}) is None


def test_only_canonical_venue_name():
    assert venue_name({"venue": {"name": "  מטבח | Example  "}}) == "מטבח | Example"
    assert venue_name({"name": "customer", "venue": "private"}) is None


async def test_two_orders_names_contract_and_reload(hass):
    ids = ["a" * 24, "b" * 24]
    labels = ["Example Kitchen", "Example Market"]
    orders = [
        {
            "purchase_id": oid,
            "venue": {"name": name, "address": "not exposed"},
            "telemetry": {"order_status_type": "IN_PROGRESS"},
        }
        for oid, name in zip(ids, labels, strict=True)
    ]
    entry = MockConfigEntry(
        domain=DOMAIN,
        options={"tracking_maps": True},
        data={
            "bearer_token": "synthetic-access",
            "refresh_token": "synthetic-refresh",
            "venue_ids": [],
        },
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"wolt_{ids[0]}",
        config_entry=entry,
        suggested_object_id="wolt_delivery_existing",
    )
    registry.async_update_entity(legacy.entity_id, name="My chosen label")
    with (
        patch.object(WoltApi, "fetch_orders", AsyncMock(return_value=orders)),
        patch.object(WoltApi, "fetch_order_details", AsyncMock(return_value={})),
        patch.object(WoltApi, "fetch_venue_location", AsyncMock(return_value={})),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        saved = {}
        for oid, label in zip(ids, labels, strict=True):
            for kind in [
                "delivery",
                "pickup",
                "destination",
                "status",
                "eta",
                "item_count",
            ]:
                eid = registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{entry.entry_id}_{oid}_{kind}"
                )
                state = hass.states.get(eid)
                assert state.attributes["venue_name"] == label
                assert "not exposed" not in str(state.attributes)
                if eid == legacy.entity_id:
                    assert state.name == "My chosen label"
                else:
                    assert label in state.name
                saved[(oid, kind)] = eid
            status_entry = registry.async_get(saved[(oid, "status")])
            device = dr.async_get(hass).async_get(status_entry.device_id)
            assert label in device.name
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        for (oid, kind), eid in saved.items():
            assert (
                registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{entry.entry_id}_{oid}_{kind}"
                )
                == eid
            )
        orders[0]["telemetry"]["order_status_type"] = "DELIVERED"
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()
        state = hass.states.get(legacy.entity_id)
        assert state.attributes["venue_name"] == labels[0]
        assert state.attributes["order_status_type"] == "DELIVERED"
        assert state.attributes["is_arriving_soon"] is False
        assert "latitude" not in state.attributes
        assert (
            hass.states.get(saved[(ids[1], "delivery")]).attributes["order_status_type"]
            == "IN_PROGRESS"
        )
