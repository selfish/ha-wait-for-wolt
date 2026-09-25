"""Per-entity location consent, independent of delivery identity."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

LEGACY_LOCATIONS = "legacy_location_entities"


def migrate_location_consent(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Snapshot only owned legacy identities, once, without enabling future orders."""
    if LEGACY_LOCATIONS in entry.data:
        return
    allowed = []
    for item in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if item.platform != DOMAIN or item.domain != "sensor":
            continue
        uid = item.unique_id
        for kind, prefix in (
            ("pickup", "wolt_pickup_"),
            ("destination", "wolt_destination_"),
            ("delivery", "wolt_"),
        ):
            if uid.startswith(prefix):
                # Venue sensors are not courier locations.
                if kind == "delivery" and uid.startswith("wolt_venue_"):
                    break
                allowed.append(f"{entry.entry_id}_{uid[len(prefix) :]}_{kind}")
                break
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, LEGACY_LOCATIONS: allowed}
    )


def location_allowed(entry: ConfigEntry, order_id: str, kind: str) -> bool:
    """Explicit opt-out overrides inherited permission; opt-in includes future orders."""
    if "tracking_maps" in entry.options or "tracking_maps" in entry.data:
        return (
            entry.options.get("tracking_maps", entry.data.get("tracking_maps")) is True
        )
    return f"{entry.entry_id}_{order_id}_{kind}" in entry.data.get(LEGACY_LOCATIONS, [])


def location_enabled(
    hass: HomeAssistant, entry: ConfigEntry, order_id: str, kind: str
) -> bool:
    """Disabled locations must not provoke public venue lookups."""
    if not location_allowed(entry, order_id, kind):
        return False
    registry = er.async_get(hass)
    uid = f"{entry.entry_id}_{order_id}_{kind}"
    legacy = f"wolt_{order_id}" if kind == "delivery" else f"wolt_{kind}_{order_id}"
    for candidate in (uid, legacy):
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, candidate)
        item = registry.async_get(entity_id) if entity_id else None
        if item is not None and item.config_entry_id == entry.entry_id:
            return item.disabled_by is None
    return True
