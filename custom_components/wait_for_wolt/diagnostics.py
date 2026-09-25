"""Default-deny, count-only diagnostics for Wait for Wolt."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Never serialize config data, registry identities or private Wolt payloads."""
    del hass
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    interval = coordinator.update_interval
    return {
        "options": {
            "tracking_maps": entry.options.get("tracking_maps") is True,
            "destination_home": entry.options.get("destination_home") is True,
        },
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
