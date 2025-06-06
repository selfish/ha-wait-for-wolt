"""Sensor platform for Wolt order tracker."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List

import aiohttp
import async_timeout
import asyncio
import voluptuous as vol

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    CONF_VENUE_IDS,
    DEFAULT_NAME,
    ACTIVE_ORDERS_URL,
    HEADERS,
    ORDER_DETAILS_URL,
    VENUE_CONTENT_URL,
    REFRESH_URL,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SESSION_ID): cv.string,
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
    venues: List[str] | None = None,
) -> None:
    """Create sensors and schedule updates."""
    session = async_get_clientsession(hass)
    api = WoltApi(session, session_id, token, refresh)

    sensors: List[WoltOrderSensor] = []
    venue_sensors: List[WoltVenueSensor] = []

    if venues:
        for slug in venues:
            venue_sensors.append(WoltVenueSensor(api, slug, f"{name} {slug}"))
        async_add_entities(venue_sensors, update_before_add=True)

    async def _update_orders(now=None) -> None:
        orders = await api.fetch_active_orders()
        known = {sensor.order_id for sensor in sensors}
        new_entities = []
        for order in orders:
            order_id = order.get("order_id")
            if not order_id or order_id in known:
                continue
            sensor = WoltOrderSensor(api, order_id, f"{name} {order_id}")
            sensors.append(sensor)
            new_entities.append(sensor)
        if new_entities:
            async_add_entities(new_entities)

    await _update_orders()
    if sensors:
        async_add_entities(sensors, update_before_add=True)
    else:
        _LOGGER.info("No active orders found")

    async_track_time_interval(hass, _update_orders, timedelta(seconds=UPDATE_INTERVAL))


class WoltApi:
    """Simple wrapper for the Wolt API."""

    def __init__(self, session: aiohttp.ClientSession, session_id: str, token: str, refresh: str) -> None:
        self._session = session
        self._session_id = session_id
        self._token = token
        self._refresh = refresh

    async def _refresh_token(self) -> None:
        """Refresh the bearer token using the refresh token."""
        payload = {"refresh_token": self._refresh}
        try:
            async with async_timeout.timeout(10):
                async with self._session.post(REFRESH_URL, json=payload, headers=HEADERS) as resp:
                    data = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:  # type: ignore[name-defined]
            _LOGGER.error("Token refresh failed: %s", err)
            return

        if "access_token" in data:
            self._token = data["access_token"]
        if "refresh_token" in data:
            self._refresh = data["refresh_token"]

    async def _request(self, method: str, url: str, auth: bool = True) -> Any:
        """Make a request and return the parsed JSON response."""
        headers = {**HEADERS}
        if auth:
            await self._refresh_token()
            headers.update(
                {
                    "w-wolt-session-id": self._session_id,
                    "authorization": f"Bearer {self._token}",
                }
            )
        try:
            async with async_timeout.timeout(10):
                async with self._session.request(method, url, headers=headers) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            aiohttp.ContentTypeError,
        ) as err:  # type: ignore[name-defined]
            _LOGGER.error("Error requesting %s: %s", url, err)
            return None

    async def fetch_active_orders(self) -> List[Dict[str, Any]]:
        data = await self._request("GET", ACTIVE_ORDERS_URL)
        return data.get("orders", []) if isinstance(data, dict) else []

    async def fetch_order_details(self, order_id: str) -> Dict[str, Any] | None:
        url = ORDER_DETAILS_URL.format(order_id)
        data = await self._request("GET", url)
        if not isinstance(data, dict):
            return None
        details = data.get("order_details") or []
        return details[0] if details else None

    async def fetch_venue_details(self, slug: str) -> Dict[str, Any] | None:
        url = VENUE_CONTENT_URL.format(slug)
        # Public endpoint - do not send authentication headers
        data = await self._request("GET", url, auth=False)
        if not isinstance(data, dict):
            return None
        venue = data.get("venue") or data.get("venue_info") or {}
        return venue


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Wolt sensors from YAML."""
    name = config[CONF_NAME]
    session_id = config[CONF_SESSION_ID]
    token = config[CONF_BEARER_TOKEN]
    refresh = config[CONF_REFRESH_TOKEN]

    venues = config.get(CONF_VENUE_IDS, [])
    await _setup_sensors(
        hass, async_add_entities, name, session_id, token, refresh, venues
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wolt sensors from a config entry."""
    data = entry.data
    venues = entry.options.get(CONF_VENUE_IDS) or data.get(CONF_VENUE_IDS, [])
    await _setup_sensors(
        hass,
        async_add_entities,
        data.get(CONF_NAME, DEFAULT_NAME),
        data[CONF_SESSION_ID],
        data[CONF_BEARER_TOKEN],
        data[CONF_REFRESH_TOKEN],
        venues,
    )


class WoltOrderSensor(SensorEntity):
    """Representation of a Wolt order sensor."""

    _attr_attribution = "Data provided by Wolt"

    def __init__(self, api: WoltApi, order_id: str, name: str) -> None:
        self.api = api
        self.order_id = order_id
        self._attr_name = name
        self._attr_unique_id = f"wolt_{order_id}"
        self._attr_extra_state_attributes = {}
        self._state = None

    @property
    def native_value(self):
        return self._state

    async def async_update(self) -> None:
        details = await self.api.fetch_order_details(self.order_id)
        if not details:
            _LOGGER.warning("Order %s details not found", self.order_id)
            return
        self._state = details.get("status")
        self._attr_extra_state_attributes = {
            "delivery_eta": details.get("delivery_eta"),
            "client_pre_estimate": details.get("client_pre_estimate"),
            "venue_name": details.get("venue_name"),
            "payment_amount": details.get("payment_amount"),
            "items": [item.get("name") for item in details.get("items", [])],
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
        self._attr_icon = "mdi:store"

    @property
    def native_value(self):
        return self._state

    async def async_update(self) -> None:
        details = await self.api.fetch_venue_details(self.slug)
        if not details:
            _LOGGER.warning("Venue %s details not found", self.slug)
            return
        is_open = details.get("online") or details.get("is_open")
        self._state = "open" if is_open else "closed"
        delivery = details.get("delivery_time") or details.get("delivery_time_min")
        delivery_max = details.get("delivery_time_max")
        self._attr_extra_state_attributes = {
            "delivery_price": details.get("delivery_price"),
            "delivery_time_min": delivery,
            "delivery_time_max": delivery_max,
        }
