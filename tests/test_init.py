"""Tests for the Wait for Wolt config-entry lifecycle."""

from unittest.mock import AsyncMock, Mock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wait_for_wolt.const import (
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    CONF_VENUE_IDS,
    DOMAIN,
)

ENTRY_DATA = {
    "name": "Sanitized Wolt",
    CONF_SESSION_ID: "sanitized-session-id",
    CONF_BEARER_TOKEN: "sanitized-access-token",
    CONF_REFRESH_TOKEN: "sanitized-refresh-token",
    CONF_VENUE_IDS: ["sanitized-venue"],
}


async def test_config_entry_setup_and_unload_cancel_polling(
    hass: HomeAssistant,
) -> None:
    """Load the sensor platform and stop its polling callback on unload."""
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    cancel_interval = Mock()

    with (
        patch(
            "custom_components.wait_for_wolt.sensor.WoltApi.fetch_active_orders",
            AsyncMock(return_value=[]),
        ),
        patch(
            "custom_components.wait_for_wolt.sensor.WoltApi.fetch_venue_details",
            AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.wait_for_wolt.sensor.async_track_time_interval",
            return_value=cancel_interval,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED

        with patch.object(
            hass.config_entries, "async_reload", AsyncMock(return_value=True)
        ) as reload_entry:
            # A user-supplied credential edit must reload the running client.
            hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_BEARER_TOKEN: "edited-access-token"},
            )
            await hass.async_block_till_done()
            reload_entry.assert_awaited_once_with(entry.entry_id)

            # Simulate the completed reload, then a client-driven token rotation.
            # The callback updates the runtime snapshot before entry persistence,
            # so this internal update must not start a reload loop.
            reload_entry.reset_mock()
            hass.data[DOMAIN][entry.entry_id] = {
                "data": dict(entry.data),
                "options": dict(entry.options),
            }
            rotated_data = {
                **entry.data,
                CONF_BEARER_TOKEN: "rotated-access-token",
                CONF_REFRESH_TOKEN: "rotated-refresh-token",
            }
            hass.data[DOMAIN][entry.entry_id]["data"] = dict(rotated_data)
            hass.config_entries.async_update_entry(entry, data=rotated_data)
            await hass.async_block_till_done()
            reload_entry.assert_not_awaited()

            hass.config_entries.async_update_entry(
                entry,
                options={CONF_VENUE_IDS: ["second-sanitized-venue"]},
            )
            await hass.async_block_till_done()
            reload_entry.assert_awaited_once_with(entry.entry_id)

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    cancel_interval.assert_called_once_with()
