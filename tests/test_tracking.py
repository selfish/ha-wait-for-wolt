"""Production compatibility, privacy and terminal-state acceptance tests."""

from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wait_for_wolt.api import WoltApi
from custom_components.wait_for_wolt.const import DOMAIN
from custom_components.wait_for_wolt.tracking import coordinates, driver_fields

DATA = {
    "bearer_token": "synthetic-access",
    "refresh_token": "synthetic-refresh",
    "venue_ids": [],
}
OID = "b" * 24
ACTIVE = {"purchase_id": OID, "telemetry": {"order_status_type": "IN_PROGRESS"}}


@pytest.mark.parametrize(
    "lat,lon",
    [
        (True, 1),
        (float("nan"), 1),
        (1, float("inf")),
        (91, 0),
        (0, -181),
        (None, None),
        ([], {}),
    ],
)
def test_bad_coordinates(lat, lon):
    assert coordinates(lat, lon) == {}


def test_driver_selection_and_allowlist():
    raw = {
        "_drivers": [
            {"location": [20, 10], "delivering_your_order": False, "phone": "private"},
            {
                "location": [40, 30],
                "delivering_your_order": True,
                "name": "private",
                "heading": 90,
            },
        ]
    }
    result = driver_fields(raw)
    assert result == {
        "longitude": 40,
        "latitude": 30,
        "delivering_your_order": True,
        "courier_heading": 90,
        "delivery_eta": None,
    }
    assert (
        driver_fields({"_drivers": [{"location": [1, 2]}, {"location": [3, 4]}]}) == {}
    )
    assert (
        driver_fields(
            {"_drivers": [{"location": [1, 2], "delivering_your_order": False}]}
        )
        == {}
    )


@pytest.mark.parametrize(
    "terminal", ["DELIVERED", "CANCELLED", "FAILED", "REJECTED", "REFUNDED", "missing"]
)
async def test_owned_legacy_migration_and_terminal_clear(hass, terminal):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy_ids = {}
    for kind, uid in (
        ("delivery", f"wolt_{OID}"),
        ("pickup", f"wolt_pickup_{OID}"),
        ("destination", f"wolt_destination_{OID}"),
    ):
        old = registry.async_get_or_create(
            "sensor",
            DOMAIN,
            uid,
            config_entry=entry,
            suggested_object_id=f"wolt_{kind}_existing",
        )
        legacy_ids[kind] = old.entity_id
    registry.async_update_entity(legacy_ids["delivery"], name="Keep my delivery name")
    hass.states.async_set("zone.home", "0", {"latitude": 12, "longitude": 34})
    future = (dt_util.utcnow() + timedelta(minutes=2)).isoformat()
    details = {
        "client_pre_estimate": {"delivery_eta": {"$date": future}},
        "_drivers": [
            {
                "location": [40, 30],
                "delivering_your_order": True,
                "name": "never expose",
            }
        ],
        "items": ["private"],
        "payment_amount": 1999,
    }
    with (
        patch.object(
            WoltApi, "fetch_orders", AsyncMock(return_value=[ACTIVE])
        ) as orders,
        patch.object(
            WoltApi, "fetch_order_details", AsyncMock(return_value=details)
        ) as tracking,
        patch.object(
            WoltApi,
            "fetch_venue_location",
            AsyncMock(return_value={"latitude": 20, "longitude": 30}),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert "tracking_maps" not in entry.data
        delivery = hass.states.get(legacy_ids["delivery"])
        assert delivery.state == "2"
        assert delivery.attributes["minutes_to_arrival"] == 2
        assert delivery.attributes["latitude"] == 30
        assert delivery.attributes["order_status_type"] == "IN_PROGRESS"
        assert delivery.attributes["friendly_name"] == "Keep my delivery name"
        assert "private" not in str(delivery.attributes)
        assert "never expose" not in str(delivery.attributes)
        assert (
            registry.async_get(legacy_ids["delivery"]).unique_id
            == f"{entry.entry_id}_{OID}_delivery"
        )
        assert (
            registry.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_{OID}_status"
            )
            != legacy_ids["delivery"]
        )
        assert hass.states.get(legacy_ids["pickup"]).attributes["latitude"] == 20
        assert (
            hass.states.get(legacy_ids["destination"]).attributes["coordinate_source"]
            == "unavailable"
        )
        orders.return_value = (
            []
            if terminal == "missing"
            else [{**ACTIVE, "telemetry": {"order_status_type": terminal}}]
        )
        tracking.reset_mock()
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()
        tracking.assert_not_awaited()
        for entity_id in legacy_ids.values():
            state = hass.states.get(entity_id)
            assert "latitude" not in state.attributes
            assert "minutes_to_arrival" not in state.attributes
            assert state.attributes.get("order_status_type") != "IN_PROGRESS"
            assert not state.attributes.get("is_arriving_soon", False)
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert entry.state is ConfigEntryState.NOT_LOADED


async def test_fresh_entry_has_no_location_entities_or_public_scraping(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=DATA)
    entry.add_to_hass(hass)
    with (
        patch.object(WoltApi, "fetch_orders", AsyncMock(return_value=[ACTIVE])),
        patch.object(WoltApi, "fetch_order_details", AsyncMock(return_value={})),
        patch.object(WoltApi, "fetch_venue_location", AsyncMock()) as page,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert (
            len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id))
            == 7
        )
        page.assert_not_awaited()


async def test_disabled_legacy_location_stays_disabled(hass):
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
        patch.object(WoltApi, "fetch_orders", AsyncMock(return_value=[ACTIVE])),
        patch.object(WoltApi, "fetch_order_details", AsyncMock(return_value={})),
        patch.object(WoltApi, "fetch_venue_location", AsyncMock(return_value={})),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert (
        registry.async_get(old.entity_id).disabled_by is er.RegistryEntryDisabler.USER
    )
    assert hass.states.get(old.entity_id) is None


async def test_other_entry_does_not_enable_maps(hass):
    other = MockConfigEntry(domain=DOMAIN, data=DATA)
    entry = MockConfigEntry(domain=DOMAIN, data=DATA)
    other.add_to_hass(hass)
    entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "sensor", DOMAIN, f"wolt_pickup_{OID}", config_entry=other
    )
    with (
        patch.object(WoltApi, "fetch_orders", AsyncMock(return_value=[ACTIVE])),
        patch.object(WoltApi, "fetch_order_details", AsyncMock(return_value={})),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert not entry.data.get("tracking_maps")
