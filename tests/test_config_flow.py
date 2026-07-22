"""Tests for UI setup and options updates."""

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wait_for_wolt import async_reload_entry
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


async def test_user_flow_parses_venue_lines(hass: HomeAssistant) -> None:
    """Create a config entry and normalize sanitized venue slugs."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **ENTRY_DATA,
            CONF_VENUE_IDS: "sanitized-venue\n second-sanitized-venue \n",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Sanitized Wolt"
    assert result["data"][CONF_VENUE_IDS] == [
        "sanitized-venue",
        "second-sanitized-venue",
    ]


async def test_user_flow_allows_missing_analytics_session(
    hass: HomeAssistant,
) -> None:
    """Create an entry when Wolt does not expose the analytics session cookie."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    user_input = {**ENTRY_DATA}
    user_input.pop(CONF_SESSION_ID)
    user_input[CONF_VENUE_IDS] = "sanitized-venue"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input,
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SESSION_ID] == ""


async def test_legacy_yaml_import_creates_one_durable_entry(
    hass: HomeAssistant,
) -> None:
    """Import YAML once so future refresh-token rotations persist in entry data."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data=ENTRY_DATA,
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Sanitized Wolt"
    assert result["data"][CONF_REFRESH_TOKEN] == "sanitized-refresh-token"

    duplicate = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data=ENTRY_DATA,
    )
    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "already_configured"


async def test_options_update_credentials_venues_and_reload(
    hass: HomeAssistant,
) -> None:
    """Persist edited credentials and venue slugs, then reload the entry."""
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA)
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_SESSION_ID: "sanitized-session-id-next",
            CONF_BEARER_TOKEN: "sanitized-access-token-next",
            CONF_REFRESH_TOKEN: "sanitized-refresh-token-next",
            CONF_VENUE_IDS: "sanitized-venue\nsecond-sanitized-venue",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_SESSION_ID] == "sanitized-session-id-next"
    assert entry.data[CONF_BEARER_TOKEN] == "sanitized-access-token-next"
    assert entry.data[CONF_REFRESH_TOKEN] == "sanitized-refresh-token-next"
    assert entry.options[CONF_VENUE_IDS] == [
        "sanitized-venue",
        "second-sanitized-venue",
    ]


async def test_credential_only_options_update_reloads_running_entry(
    hass: HomeAssistant,
) -> None:
    """Reload when credentials change but the venue options stay identical."""
    options = {CONF_VENUE_IDS: ["sanitized-venue"]}
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, options=options)
    entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "data": dict(entry.data),
        "options": dict(entry.options),
    }
    entry.add_update_listener(async_reload_entry)

    with patch.object(
        hass.config_entries, "async_reload", AsyncMock(return_value=True)
    ) as reload_entry:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_SESSION_ID: "sanitized-session-id-next",
                CONF_BEARER_TOKEN: "sanitized-access-token-next",
                CONF_REFRESH_TOKEN: "sanitized-refresh-token-next",
                CONF_VENUE_IDS: "sanitized-venue",
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    reload_entry.assert_awaited_once_with(entry.entry_id)
