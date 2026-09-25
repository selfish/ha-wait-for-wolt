"""Non-purchase legacy identities must not be reused as tracking sensors."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wait_for_wolt.const import DOMAIN
from custom_components.wait_for_wolt.privacy import LEGACY_LOCATIONS


@pytest.mark.parametrize("from_b1", [False, True])
@pytest.mark.parametrize("disabled", [None, er.RegistryEntryDisabler.USER])
async def test_monthly_spend_is_not_a_purchase(hass, from_b1, disabled):
    entry = MockConfigEntry(
        domain=DOMAIN, data={"bearer_token": "synthetic", "refresh_token": "synthetic"}
    )
    entry.add_to_hass(hass)
    accidental = f"{entry.entry_id}_monthly_spend_delivery"
    if from_b1:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, LEGACY_LOCATIONS: [accidental]}
        )
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        accidental if from_b1 else "wolt_monthly_spend",
        config_entry=entry,
        suggested_object_id="wolt_monthly_spend",
    )
    registry.async_update_entity(
        old.entity_id, name="My spending", disabled_by=disabled
    )
    with patch(
        "custom_components.wait_for_wolt.api.WoltApi.fetch_orders",
        new=AsyncMock(return_value=[]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        item = registry.async_get(old.entity_id)
        assert item.unique_id == "wolt_monthly_spend"
        assert item.name == "My spending"
        assert item.disabled_by == disabled
        assert entry.data[LEGACY_LOCATIONS] == []
        assert hass.states.get(old.entity_id) is None
        assert not any(
            "delivery" in s.entity_id for s in hass.states.async_all("sensor")
        )
