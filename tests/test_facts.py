"""Synthetic fixtures matching audited field shapes, never live payloads."""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wait_for_wolt.api import WoltApi
from custom_components.wait_for_wolt.const import DOMAIN
from custom_components.wait_for_wolt.facts import (
    dropoff_coordinates,
    item_count,
    money,
    summary_total,
)
from custom_components.wait_for_wolt.privacy import is_purchase_id


@pytest.mark.parametrize("value", [True, -1, 1.5, "100", None, {}, []])
def test_money_rejects_ambiguous_or_malformed_amounts(value):
    assert money({"currency": "ILS", "price": value}, "price")[0] is None


@pytest.mark.parametrize(
    "currency,amount,expected",
    [("ILS", 1234, "12.34"), ("JPY", 1234, "1234"), ("KWD", 1234, "1.234")],
)
def test_explicit_minor_units(currency, amount, expected):
    assert money({"currency": currency, "price": amount}, "price") == (
        Decimal(expected),
        currency,
    )


def test_unknown_currency_and_ambiguous_summary_are_unknown():
    assert money({"currency": "XXX", "price": 10}, "price") == (None, None)
    assert summary_total({"total": "$10.00", "telemetry": {"end_amount": 1000}}) == (
        None,
        None,
    )
    assert (
        summary_total({"total": "₪10.00", "telemetry": {"end_amount": 900}})[0] is None
    )
    assert summary_total(
        {"total": "€1,234.56", "telemetry": {"end_amount": 123456}}
    ) == (Decimal("1234.56"), "EUR")


@pytest.mark.parametrize(
    "items,expected",
    [
        ([], 0),
        ([{"count": 2}, {"count": 3}], 5),
        ([{"count": True}], None),
        ([{"count": -1}], None),
        ([{}], None),
        (None, None),
    ],
)
def test_item_quantities(items, expected):
    assert item_count({"items": items}) == expected


@pytest.mark.parametrize(
    "point",
    [
        None,
        {"type": "LineString", "coordinates": [34, 12]},
        {"type": "Point", "coordinates": [True, 12]},
        {"type": "Point", "coordinates": [34, 91]},
        {"type": "Point", "coordinates": [float("nan"), 12]},
        {"type": "Point", "coordinates": [34, 12, 1]},
    ],
)
def test_bad_geojson_is_not_a_destination(point):
    assert dropoff_coordinates({"delivery_location": {"coordinates": point}}) is None


def test_only_canonical_registry_identities_are_purchase_candidates():
    assert is_purchase_id("a" * 24)
    for value in ("configuration", "a" * 23, "z" * 24, None):
        assert not is_purchase_id(value)


@pytest.mark.parametrize("maps", [False, True])
async def test_fact_entities_privacy_units_and_terminal_cleanup(hass, maps):
    oid = "a" * 24
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"bearer_token": "synthetic", "refresh_token": "synthetic"},
        options={"tracking_maps": maps},
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    # Explicit user enables the optional financial sensors.
    for kind in ("total", "delivery_fee", "service_fee"):
        registry.async_get_or_create(
            "sensor", DOMAIN, f"{entry.entry_id}_{oid}_{kind}", config_entry=entry
        )
    order = {
        "purchase_id": oid,
        "telemetry": {"order_status_type": "IN_PROGRESS", "end_amount": 1099},
        "total": "₪10.99",
        "items": [{"count": 2}, {"count": 3}],
    }
    detail = {
        "currency": "ILS",
        "total_price": 1099,
        "delivery_price": 100,
        "service_fee": 50,
        "payment_time": {"$date": 1893456000000},
        "delivery_location": {
            "coordinates": {"type": "Point", "coordinates": [34, 12]},
            "street": "private-street",
        },
        "payment_info": {"card": "private-card"},
    }

    def state(kind):
        eid = registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{oid}_{kind}"
        )
        return hass.states.get(eid) if eid else None

    with (
        patch.object(WoltApi, "fetch_orders", AsyncMock(return_value=[order])),
        patch.object(
            WoltApi, "fetch_order_details", AsyncMock(return_value=detail)
        ) as rich,
        patch.object(WoltApi, "fetch_venue_location", AsyncMock(return_value={})),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert state("item_count").state == "5"
        assert Decimal(state("total").state) == Decimal("10.99")
        assert state("total").attributes["unit_of_measurement"] == "ILS"
        assert Decimal(state("delivery_fee").state) == 1
        assert Decimal(state("service_fee").state) == Decimal("0.50")
        assert state("status").attributes["payment_time"] == "2030-01-01T00:00:00+00:00"
        if maps:
            assert state("destination").attributes["latitude"] == 12
            assert state("destination").attributes["longitude"] == 34
            assert (
                state("destination").attributes["coordinate_source"] == "wolt_dropoff"
            )
        else:
            assert state("destination") is None
        for entity in hass.states.async_all():
            assert "private-street" not in str(entity.attributes)
            assert "private-card" not in str(entity.attributes)
        order["telemetry"]["order_status_type"] = "DELIVERED"
        await entry.runtime_data.coordinator.async_request_refresh()
        await hass.async_block_till_done()
        assert rich.await_count == 1
        assert state("delivery_fee").state == "unknown"
        assert state("service_fee").state == "unknown"
        assert Decimal(state("total").state) == Decimal("10.99")
        assert "payment_time" not in state("status").attributes
        if maps:
            assert "latitude" not in state("destination").attributes


async def test_optional_financial_entities_are_disabled_by_default(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"bearer_token": "synthetic", "refresh_token": "synthetic"},
    )
    entry.add_to_hass(hass)
    oid = "a" * 24
    with (
        patch.object(
            WoltApi,
            "fetch_orders",
            AsyncMock(
                return_value=[
                    {
                        "purchase_id": oid,
                        "telemetry": {"order_status_type": "IN_PROGRESS"},
                    }
                ]
            ),
        ),
        patch.object(WoltApi, "fetch_order_details", AsyncMock(return_value={})),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        registry = er.async_get(hass)
        for kind in ("total", "delivery_fee", "service_fee"):
            eid = registry.async_get_entity_id(
                "sensor", DOMAIN, f"{entry.entry_id}_{oid}_{kind}"
            )
            assert (
                registry.async_get(eid).disabled_by
                is er.RegistryEntryDisabler.INTEGRATION
            )
            assert hass.states.get(eid) is None


@pytest.mark.parametrize("scoped", [False, True])
async def test_arbitrary_registry_suffix_does_not_create_a_purchase(hass, scoped):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"bearer_token": "synthetic", "refresh_token": "synthetic"},
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    uid = f"{entry.entry_id}_configuration_delivery" if scoped else "wolt_configuration"
    original = registry.async_get_or_create("sensor", DOMAIN, uid, config_entry=entry)
    with patch.object(WoltApi, "fetch_orders", AsyncMock(return_value=[])):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert registry.async_get(original.entity_id).unique_id == uid
        assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == 1
        assert not entry.data["legacy_location_entities"]
        state = hass.states.get(original.entity_id)
        assert state is None or state.state == "unavailable"
