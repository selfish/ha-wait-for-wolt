"""Wolt order tracker integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List

import aiohttp
import async_timeout
import voluptuous as vol

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_SESSION_ID,
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    DEFAULT_NAME,
    UPDATE_INTERVAL,
    HEADERS,
    REFRESH_URL,
    ACTIVE_ORDERS_URL,
    ORDER_DETAILS_URL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SESSION_ID): cv.string,
        vol.Required(CONF_BEARER_TOKEN): cv.string,
        vol.Required(CONF_REFRESH_TOKEN): cv.string,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    }
)


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

    async def _request(self, method: str, url: str) -> Any:
        await self._refresh_token()
        headers = {
            **HEADERS,
            "w-wolt-session-id": self._session_id,
            "authorization": f"Bearer {self._token}",
        }
        try:
            async with async_timeout.timeout(10):
                async with self._session.request(method, url, headers=headers) as resp:
                    return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:  # type: ignore[name-defined]
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


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Wolt order sensors."""
    name = config[CONF_NAME]
    session_id = config[CONF_SESSION_ID]
    token = config[CONF_BEARER_TOKEN]
    refresh = config[CONF_REFRESH_TOKEN]

    session = async_get_clientsession(hass)
    api = WoltApi(session, session_id, token, refresh)

    sensors: List[WoltOrderSensor] = []

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
