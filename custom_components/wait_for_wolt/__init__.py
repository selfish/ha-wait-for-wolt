"""Wolt order tracker integration."""

from __future__ import annotations

import uuid

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import WoltApi
from .const import (
    CONF_BEARER_TOKEN,
    CONF_CLIENT_ID,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    DOMAIN,
)
from .coordinator import WoltDataUpdateCoordinator, WoltRuntimeData

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.platform_only_config_schema(DOMAIN)


def _entry_snapshot(entry: ConfigEntry) -> dict[str, dict]:
    """Return the entry values used by the currently loaded runtime."""
    return {"data": dict(entry.data), "options": dict(entry.options)}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up via YAML (handled by the sensor platform)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Create the shared client/coordinator and set up entry platforms."""
    # One-time compatibility migration: preserve existing household map/arrival
    # automations. New installs remain private by default. Explicit false wins.
    if "tracking_maps" not in entry.data and "tracking_maps" not in entry.options:
        legacy = any(
            item.platform == DOMAIN
            and (
                item.unique_id.startswith(("wolt_pickup_", "wolt_destination_"))
                or item.entity_id.startswith("sensor.wolt_delivery_")
            )
            for item in er.async_entries_for_config_entry(
                er.async_get(hass), entry.entry_id
            )
        )
        if legacy:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, "tracking_maps": True}
            )
    if not entry.data.get(CONF_CLIENT_ID):
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_CLIENT_ID: str(uuid.uuid4())},
        )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = _entry_snapshot(entry)

    def persist_tokens(access_token: str, refresh_token: str) -> None:
        """Persist Wolt credential rotation without reloading the runtime."""
        updated_data = {
            **entry.data,
            CONF_BEARER_TOKEN: access_token,
            CONF_REFRESH_TOKEN: refresh_token,
        }
        runtime_snapshot = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if isinstance(runtime_snapshot, dict):
            runtime_snapshot["data"] = dict(updated_data)
            runtime_snapshot["options"] = dict(entry.options)
        hass.config_entries.async_update_entry(entry, data=updated_data)

    api = WoltApi(
        async_get_clientsession(hass),
        entry.data.get(CONF_SESSION_ID, ""),
        entry.data[CONF_BEARER_TOKEN],
        entry.data[CONF_REFRESH_TOKEN],
        client_id=entry.data[CONF_CLIENT_ID],
        token_update_callback=persist_tokens,
    )
    coordinator = WoltDataUpdateCoordinator(hass, entry, api)
    entry.runtime_data = WoltRuntimeData(api, coordinator)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.async_on_unload(entry.add_update_listener(async_reload_entry))
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload after user options change, but not after token rotation."""
    if hass.data.get(DOMAIN, {}).get(entry.entry_id) == _entry_snapshot(entry):
        return
    await hass.config_entries.async_reload(entry.entry_id)
