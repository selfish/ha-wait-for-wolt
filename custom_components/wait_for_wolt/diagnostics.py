"""Privacy-preserving diagnostics for Wait for Wolt."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant

from .const import (
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    CONF_VENUE_IDS,
)

TO_REDACT = {
    CONF_NAME,
    CONF_SESSION_ID,
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_VENUE_IDS,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return operational counts without order, courier, venue, or credential data."""
    del hass
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    interval = coordinator.update_interval
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "known_order_count": len(data.orders),
            "active_order_count": len(data.active_order_ids),
            "rich_detail_count": len(data.details),
            "update_interval_seconds": (
                int(interval.total_seconds()) if interval is not None else None
            ),
        },
    }
