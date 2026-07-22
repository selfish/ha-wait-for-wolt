"""Tests for the Wait for Wolt config-entry lifecycle."""

from unittest.mock import AsyncMock, Mock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wait_for_wolt.api import (
    WoltApi,
    WoltAuthenticationError,
    WoltConnectionError,
)
from custom_components.wait_for_wolt.const import (
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    CONF_VENUE_IDS,
    DOMAIN,
)
from custom_components.wait_for_wolt.coordinator import WoltCoordinatorData

ENTRY_DATA = {
    "name": "Sanitized Wolt",
    CONF_SESSION_ID: "sanitized-session-id",
    CONF_BEARER_TOKEN: "sanitized-access-token",
    CONF_REFRESH_TOKEN: "sanitized-refresh-token",
    CONF_VENUE_IDS: [],
}


async def test_config_entry_setup_rotation_reload_and_unload(
    hass: HomeAssistant,
) -> None:
    """Own one coordinator, persist rotation, reload user edits, and unload."""
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)
    api = Mock()
    coordinator = Mock()
    coordinator.data = WoltCoordinatorData({}, frozenset(), {})
    coordinator.async_config_entry_first_refresh = AsyncMock()
    cancel_listener = Mock()
    coordinator.async_add_listener.return_value = cancel_listener

    with (
        patch(
            "custom_components.wait_for_wolt.WoltApi",
            return_value=api,
        ) as api_class,
        patch(
            "custom_components.wait_for_wolt.WoltDataUpdateCoordinator",
            return_value=coordinator,
        ) as coordinator_class,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        coordinator.async_config_entry_first_refresh.assert_awaited_once_with()
        coordinator_class.assert_called_once_with(hass, entry, api)

        token_callback = api_class.call_args.kwargs["token_update_callback"]
        with patch.object(
            hass.config_entries, "async_reload", AsyncMock(return_value=True)
        ) as reload_entry:
            token_callback("rotated-access-token", "rotated-refresh-token")
            await hass.async_block_till_done()
            assert entry.data[CONF_BEARER_TOKEN] == "rotated-access-token"
            assert entry.data[CONF_REFRESH_TOKEN] == "rotated-refresh-token"
            reload_entry.assert_not_awaited()

            hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_BEARER_TOKEN: "edited-access-token"},
            )
            await hass.async_block_till_done()
            reload_entry.assert_awaited_once_with(entry.entry_id)

            # Simulate the completed reload before checking an options-only edit.
            reload_entry.reset_mock()
            hass.data[DOMAIN][entry.entry_id] = {
                "data": dict(entry.data),
                "options": dict(entry.options),
            }
            hass.config_entries.async_update_entry(
                entry,
                options={CONF_VENUE_IDS: ["second-sanitized-venue"]},
            )
            await hass.async_block_till_done()
            reload_entry.assert_awaited_once_with(entry.entry_id)

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    cancel_listener.assert_called_once_with()


async def test_transient_first_refresh_enters_setup_retry(
    hass: HomeAssistant,
) -> None:
    """Use Home Assistant's retry lifecycle when Wolt is temporarily offline."""
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    with patch.object(
        WoltApi,
        "fetch_orders",
        AsyncMock(side_effect=WoltConnectionError("offline")),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_auth_first_refresh_starts_reauthentication(
    hass: HomeAssistant,
) -> None:
    """Open the credential-replacement flow when Wolt rejects the entry."""
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    with patch.object(
        WoltApi,
        "fetch_orders",
        AsyncMock(side_effect=WoltAuthenticationError("rejected", status=401)),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == "reauth"
    assert flows[0]["context"]["entry_id"] == entry.entry_id
