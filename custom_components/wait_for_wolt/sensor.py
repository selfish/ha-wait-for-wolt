"""Sensor platform for Wolt order tracker."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .api import WoltApi, WoltApiError
from .const import (
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    CONF_VENUE_IDS,
    DEFAULT_NAME,
    DOMAIN,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_SESSION_ID, default=""): cv.string,
        vol.Required(CONF_BEARER_TOKEN): cv.string,
        vol.Required(CONF_REFRESH_TOKEN): cv.string,
        vol.Optional(CONF_VENUE_IDS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    }
)


async def _setup_sensors(
    hass: HomeAssistant,
    async_add_entities: AddEntitiesCallback,
    name: str,
    session_id: str,
    token: str,
    refresh: str,
    venues: list[str] | None = None,
    entry: ConfigEntry | None = None,
) -> Callable[[], None]:
    """Create sensors and schedule updates."""
    session = async_get_clientsession(hass)

    def _persist_tokens(access_token: str, refresh_token: str) -> None:
        if entry is None:
            return
        updated_data = {
            **entry.data,
            CONF_BEARER_TOKEN: access_token,
            CONF_REFRESH_TOKEN: refresh_token,
        }
        runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if isinstance(runtime, dict):
            runtime["data"] = dict(updated_data)
            runtime["options"] = dict(entry.options)
        hass.config_entries.async_update_entry(
            entry,
            data=updated_data,
        )

    api = WoltApi(
        session,
        session_id,
        token,
        refresh,
        token_update_callback=_persist_tokens if entry is not None else None,
    )

    sensors: list[WoltOrderSensor] = []
    venue_sensors: list[WoltVenueSensor] = []

    if venues:
        for slug in venues:
            venue_sensors.append(WoltVenueSensor(api, slug, f"{name} {slug}"))
        async_add_entities(venue_sensors, update_before_add=True)

    async def _update_orders(now=None, *, update_before_add: bool = False) -> None:
        try:
            orders = await api.fetch_active_orders()
        except WoltApiError as err:
            _LOGGER.warning("Unable to fetch active Wolt orders: %s", err)
            return
        known = {sensor.order_id for sensor in sensors}
        new_entities = []
        for order in orders:
            order_id = order.get("purchase_id") or order.get("order_id")
            if not order_id or order_id in known:
                continue
            sensor = WoltOrderSensor(api, order_id, f"{name} {order_id}")
            sensors.append(sensor)
            new_entities.append(sensor)
        if new_entities:
            async_add_entities(new_entities, update_before_add=update_before_add)

    await _update_orders(update_before_add=True)
    if not sensors:
        _LOGGER.info("No active orders found")

    return async_track_time_interval(
        hass, _update_orders, timedelta(seconds=UPDATE_INTERVAL)
    )


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Import legacy YAML into a config entry with durable token rotation."""
    del async_add_entities, discovery_info
    _LOGGER.warning(
        "YAML configuration for wait_for_wolt is deprecated; importing it into "
        "the Home Assistant integration UI. Remove the YAML after import"
    )
    await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={
            CONF_NAME: config[CONF_NAME],
            CONF_SESSION_ID: config.get(CONF_SESSION_ID, ""),
            CONF_BEARER_TOKEN: config[CONF_BEARER_TOKEN],
            CONF_REFRESH_TOKEN: config[CONF_REFRESH_TOKEN],
            CONF_VENUE_IDS: config.get(CONF_VENUE_IDS, []),
        },
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wolt sensors from a config entry."""
    data = {**entry.data, **entry.options}
    venues = data.get(CONF_VENUE_IDS, [])
    cancel_interval = await _setup_sensors(
        hass,
        async_add_entities,
        data.get(CONF_NAME, DEFAULT_NAME),
        data.get(CONF_SESSION_ID, ""),
        data[CONF_BEARER_TOKEN],
        data[CONF_REFRESH_TOKEN],
        venues,
        entry,
    )
    entry.async_on_unload(cancel_interval)


class WoltOrderSensor(SensorEntity):
    """Representation of a Wolt order sensor."""

    _attr_attribution = "Data provided by Wolt"

    def __init__(self, api: WoltApi, order_id: str, name: str) -> None:
        self.api = api
        self.order_id = order_id
        self._attr_name = name
        self._attr_unique_id = f"wolt_{order_id}"
        self._attr_extra_state_attributes = {}
        self._attr_available = False
        self._state = None

    @property
    def native_value(self):
        return self._state

    async def async_update(self) -> None:
        try:
            details = await self.api.fetch_order_details(self.order_id)
        except WoltApiError as err:
            self._attr_available = False
            _LOGGER.warning("Unable to update Wolt order %s: %s", self.order_id, err)
            return
        if not details:
            self._attr_available = False
            _LOGGER.warning("Order %s details not found", self.order_id)
            return
        self._attr_available = True
        status = details.get("status")
        if isinstance(status, dict):
            status = status.get("value") or status.get("text") or status.get("label")
        if status is None:
            status = details.get("order_status_type")
        self._state = str(status) if status is not None else None
        items = details.get("items")
        self._attr_extra_state_attributes = {
            "delivery_eta": details.get("delivery_eta"),
            "client_pre_estimate": details.get("client_pre_estimate"),
            "venue_name": details.get("venue_name"),
            "payment_amount": details.get("payment_amount"),
            "items": [item.get("name") for item in items if isinstance(item, dict)]
            if isinstance(items, list)
            else [],
        }
        self._attr_icon = "mdi:package-variant"


class WoltVenueSensor(SensorEntity):
    """Sensor representing a Wolt venue's availability."""

    _attr_attribution = "Data provided by Wolt"

    def __init__(self, api: WoltApi, slug: str, name: str) -> None:
        self.api = api
        self.slug = slug
        self._attr_name = name
        self._attr_unique_id = f"wolt_venue_{slug}"
        self._state = None
        self._attr_extra_state_attributes = {}
        self._attr_available = False
        self._attr_icon = "mdi:store"

    @property
    def native_value(self):
        return self._state

    async def async_update(self) -> None:
        try:
            details = await self.api.fetch_venue_details(self.slug)
        except WoltApiError as err:
            self._attr_available = False
            _LOGGER.warning("Unable to update Wolt venue %s: %s", self.slug, err)
            return
        if not details:
            self._attr_available = False
            _LOGGER.warning("Venue %s details not found", self.slug)
            return

        venue = details.get("venue") or details.get("venue_info") or {}
        self._attr_available = True
        open_info = venue.get("delivery_open_status") or venue.get("open_status") or {}

        is_open = (
            open_info.get("is_open") or venue.get("online") or venue.get("is_open")
        )
        self._state = "open" if is_open else "closed"

        # Extract estimates for available delivery methods
        estimates: dict[str, Any] = {}
        for cfg in venue.get("delivery_configs", []):
            method = cfg.get("method")
            estimate = cfg.get("estimate") or {}
            if method and estimate:
                estimates[f"{method}_estimate_min"] = estimate.get("min")
                estimates[f"{method}_estimate_max"] = estimate.get("max")

        # Parse useful metadata from the header section
        header = venue.get("header", {})
        statuses = (
            header.get("delivery_method_statuses", [])
            if isinstance(header, dict)
            else []
        )
        meta = (
            statuses[0].get("metadata", [])
            if statuses and isinstance(statuses[0], dict)
            else []
        )
        rating = None
        delivery_fee = None
        service_fee = None
        min_order_text = None
        for item in meta:
            icon = item.get("icon")
            value = item.get("value")
            if icon and icon.startswith("RATING"):
                rating = value
            elif icon == "CYCLIST":
                delivery_fee = value
            elif value and "Min. order" in value:
                min_order_text = value
            elif value and "Service fee" in value:
                service_fee = value

        banner_text = None
        if venue.get("banners"):
            banner = venue["banners"][0]
            discount = banner.get("discount") or banner
            banner_text = discount.get("formatted_text")

        self._attr_extra_state_attributes = {
            "online": venue.get("online"),
            "open_status": open_info.get("value"),
            "next_open": open_info.get("next_open"),
            "next_close": open_info.get("next_close"),
            "order_minimum": details.get("order_minimum"),
            "is_venue_favourite": details.get("is_venue_favourite"),
            "rating": rating,
            "delivery_fee": delivery_fee,
            "service_fee": service_fee,
            "min_order_text": min_order_text,
            "discount": banner_text,
            **estimates,
        }
