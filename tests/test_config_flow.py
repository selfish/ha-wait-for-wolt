"""Tests for UI setup and options updates."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
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
    assert entry.data == ENTRY_DATA
    assert entry.options[CONF_SESSION_ID] == "sanitized-session-id-next"
    assert entry.options[CONF_BEARER_TOKEN] == "sanitized-access-token-next"
    assert entry.options[CONF_REFRESH_TOKEN] == "sanitized-refresh-token-next"
    assert entry.options[CONF_VENUE_IDS] == [
        "sanitized-venue",
        "second-sanitized-venue",
    ]
