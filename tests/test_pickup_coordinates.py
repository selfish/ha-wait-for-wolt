"""Canonical pickup geometry, consent, fallback and terminal cleanup."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wait_for_wolt.api import WoltApi
from custom_components.wait_for_wolt.const import DOMAIN
from custom_components.wait_for_wolt.facts import pickup_coordinates


@pytest.mark.parametrize(
    "point",
    [
        None,
        {},
        [],
        [1],
        [1, 2, 3],
        [True, 12],
        [34, False],
        ["34", 12],
        [float("nan"), 12],
        [34, float("inf")],
        [181, 12],
        [34, 91],
        [-181, 12],
        [34, -91],
        [10**1000, 12],
        (40, 30),
    ],
)
def test_invalid_pickup_points(point):
    assert pickup_coordinates({"venue_coordinates": point}) is None


def test_pickup_coordinate_order_and_zero():
    assert pickup_coordinates({"venue_coordinates": [40, 30]}) == (30.0, 40.0)
    assert pickup_coordinates({"venue_coordinates": [0, 0]}) == (0.0, 0.0)


@pytest.mark.parametrize("maps", [False, True])
@pytest.mark.parametrize(
    "point,expected_source",
    [
        ([40, 30], "wolt_order_details"),
        (None, "wolt_venue_json_ld"),
        ([181, 20], "wolt_venue_json_ld"),
    ],
)
async def test_pickup_source_consent_and_cleanup(hass, maps, point, expected_source):
    oid = "c" * 24
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"bearer_token": "synthetic", "refresh_token": "synthetic"},
        options={"tracking_maps": maps},
    )
    entry.add_to_hass(hass)
    order = {"purchase_id": oid, "telemetry": {"order_status_type": "IN_PROGRESS"}}
    details = {"venue_coordinates": point, "venue_address": "never expose"}
    with (
        patch.object(WoltApi, "fetch_orders", AsyncMock(return_value=[order])),
        patch.object(WoltApi, "fetch_order_details", AsyncMock(return_value=details)),
        patch.object(
            WoltApi,
            "fetch_venue_location",
            AsyncMock(return_value={"latitude": 10, "longitude": 20}),
        ) as page,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        eid = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{oid}_pickup"
        )
        if not maps:
            assert eid is None
            assert not entry.runtime_data.coordinator.data.pickups
            page.assert_not_awaited()
            return
        state = hass.states.get(eid)
        assert state.attributes["coordinate_source"] == expected_source
        assert state.attributes["latitude"] == (
            30 if expected_source == "wolt_order_details" else 10
        )
        assert state.attributes["longitude"] == (
            40 if expected_source == "wolt_order_details" else 20
        )
        assert "never expose" not in str(state.attributes)
        if expected_source == "wolt_order_details":
            page.assert_not_awaited()
        else:
            page.assert_awaited_once()
        order["telemetry"]["order_status_type"] = "DELIVERED"
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()
        state = hass.states.get(eid)
        assert state.state == "inactive"
        assert "latitude" not in state.attributes
        assert "longitude" not in state.attributes
        assert state.attributes["coordinate_source"] == "unavailable"
