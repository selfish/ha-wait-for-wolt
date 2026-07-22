"""Tests for privacy-preserving Wolt diagnostics."""

import json
from datetime import timedelta
from unittest.mock import Mock

from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wait_for_wolt.const import (
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    CONF_VENUE_IDS,
    DOMAIN,
)
from custom_components.wait_for_wolt.coordinator import (
    WoltCoordinatorData,
    WoltRuntimeData,
)
from custom_components.wait_for_wolt.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_expose_counts_without_credentials_or_order_pii(
    hass: HomeAssistant,
) -> None:
    """Keep diagnostics useful without serializing private Wolt payloads."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_NAME: "Private account name",
            CONF_SESSION_ID: "private-session-id",
            CONF_BEARER_TOKEN: "private-access-token",
            CONF_REFRESH_TOKEN: "private-refresh-token",
        },
        options={CONF_VENUE_IDS: ["private-venue-slug"]},
    )
    coordinator = Mock()
    coordinator.data = WoltCoordinatorData(
        orders={
            "private-purchase-id": {
                "purchase_id": "private-purchase-id",
                "address": "Private address",
            }
        },
        active_order_ids=frozenset({"private-purchase-id"}),
        details={
            "private-purchase-id": {
                "driver_name": "Private courier",
                "items": [{"name": "Private item"}],
            }
        },
    )
    coordinator.last_update_success = True
    coordinator.update_interval = timedelta(seconds=30)
    entry.runtime_data = WoltRuntimeData(Mock(), coordinator)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    serialized = json.dumps(diagnostics)

    for private_value in (
        "Private account name",
        "private-session-id",
        "private-access-token",
        "private-refresh-token",
        "private-venue-slug",
        "private-purchase-id",
        "Private address",
        "Private courier",
        "Private item",
    ):
        assert private_value not in serialized
    assert diagnostics["coordinator"] == {
        "last_update_success": True,
        "known_order_count": 1,
        "active_order_count": 1,
        "rich_detail_count": 1,
        "update_interval_seconds": 30,
    }
