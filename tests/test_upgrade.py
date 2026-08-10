"""Offline upgrade acceptance tests through Home Assistant's real lifecycle."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wait_for_wolt.api import WoltApi, WoltAuthenticationError
from custom_components.wait_for_wolt.const import (
    CONF_BEARER_TOKEN,
    CONF_CLIENT_ID,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    CONF_VENUE_IDS,
    DOMAIN,
)

ENTRY_DATA = {
    CONF_NAME: "Synthetic upgrade account",
    CONF_SESSION_ID: "synthetic-session-not-valid",
    CONF_BEARER_TOKEN: "synthetic-access-not-valid",
    CONF_REFRESH_TOKEN: "synthetic-refresh-not-valid",
    CONF_VENUE_IDS: [],
}


async def test_yaml_platform_import_creates_loaded_durable_entry(
    hass: HomeAssistant,
) -> None:
    """Exercise YAML schema, import flow, and config-entry setup without network."""
    config = {"sensor": [{"platform": DOMAIN, **ENTRY_DATA}]}
    with patch.object(WoltApi, "fetch_orders", AsyncMock(return_value=[])):
        assert await async_setup_component(hass, "sensor", config)
        await hass.async_block_till_done()

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].state is ConfigEntryState.LOADED
    assert entries[0].data[CONF_REFRESH_TOKEN] == ENTRY_DATA[CONF_REFRESH_TOKEN]


async def test_reauth_validates_then_recovers_to_loaded(
    hass: HomeAssistant,
) -> None:
    """Exercise setup failure, validated reauth, and replacement setup."""
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    fetch_orders = AsyncMock(
        side_effect=[
            WoltAuthenticationError("synthetic rejection", status=401),
            [],
            [],
        ]
    )

    with patch.object(WoltApi, "fetch_orders", fetch_orders):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.SETUP_ERROR
        stable_client_id = entry.data[CONF_CLIENT_ID]

        flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
        assert len(flows) == 1
        assert flows[0]["context"]["source"] == SOURCE_REAUTH
        result = await hass.config_entries.flow.async_configure(
            flows[0]["flow_id"],
            {
                CONF_SESSION_ID: "",
                CONF_BEARER_TOKEN: "",
                CONF_REFRESH_TOKEN: "synthetic-replacement-refresh-not-valid",
            },
        )
        assert result["type"] is FlowResultType.ABORT
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_REFRESH_TOKEN] == "synthetic-replacement-refresh-not-valid"
    assert entry.data[CONF_CLIENT_ID] == stable_client_id
    assert fetch_orders.await_count == 3


async def test_restart_rebuild_uses_persisted_rotated_credentials(
    hass: HomeAssistant,
) -> None:
    """Prove token rotation survives an unload and restart-like setup."""
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    with patch.object(WoltApi, "fetch_orders", AsyncMock(return_value=[])):
        assert await hass.config_entries.async_setup(entry.entry_id)
        first_api = entry.runtime_data.api
        first_api._token_update_callback(
            "synthetic-rotated-access-not-valid",
            "synthetic-rotated-refresh-not-valid",
        )
        await hass.async_block_till_done()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert await hass.config_entries.async_setup(entry.entry_id)

    second_api = entry.runtime_data.api
    assert second_api is not first_api
    assert second_api.access_token == "synthetic-rotated-access-not-valid"
    assert second_api.refresh_token == "synthetic-rotated-refresh-not-valid"
    assert entry.state is ConfigEntryState.LOADED


async def test_real_platform_migrates_historical_entity_and_state(
    hass: HomeAssistant,
) -> None:
    """Exercise registry migration through the actual sensor platform."""
    order_id = "synthetic-purchase-001"
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    legacy = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"wolt_{order_id}",
        config_entry=entry,
        suggested_object_id="legacy_wolt_order",
        original_name="Historical order",
    )
    registry.async_update_entity(legacy.entity_id, name="Keep this custom name")
    summary = {
        "purchase_id": order_id,
        "status": {"value": "Delivered"},
        "telemetry": {"order_status_type": "DELIVERED"},
    }

    with patch.object(WoltApi, "fetch_orders", AsyncMock(return_value=[summary])):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    migrated = registry.async_get(legacy.entity_id)
    assert migrated is not None
    assert migrated.entity_id == legacy.entity_id
    assert migrated.unique_id == f"{entry.entry_id}_{order_id}_status"
    assert migrated.name == "Keep this custom name"
    state = hass.states.get(legacy.entity_id)
    assert state is not None
    assert state.state == "delivered"
    assert entry.state is ConfigEntryState.LOADED
