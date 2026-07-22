"""Sensor platform for Wolt order tracker."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import WoltApi, WoltApiError
from .const import (
    CONF_BEARER_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_SESSION_ID,
    CONF_VENUE_IDS,
    DEFAULT_NAME,
    DOMAIN,
)
from .coordinator import WoltDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_SESSION_ID, default=""): cv.string,
        vol.Required(CONF_BEARER_TOKEN): cv.string,
        vol.Required(CONF_REFRESH_TOKEN): cv.string,
        vol.Optional(CONF_VENUE_IDS, default=[]): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    }
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
    """Set up coordinator-backed order sensors and public venue sensors."""
    data = {**entry.data, **entry.options}
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    api = runtime.api
    name = data.get(CONF_NAME, DEFAULT_NAME)
    venues = data.get(CONF_VENUE_IDS, [])
    if venues:
        async_add_entities(
            [WoltVenueSensor(api, slug, f"{name} {slug}") for slug in venues],
            update_before_add=True,
        )

    known_order_ids: set[str] = set()

    @callback
    def async_add_new_orders() -> None:
        new_order_ids = coordinator.data.active_order_ids - known_order_ids
        if not new_order_ids:
            return
        known_order_ids.update(new_order_ids)
        async_add_entities(
            [
                WoltOrderSensor(coordinator, order_id, f"{name} {order_id}")
                for order_id in sorted(new_order_ids)
            ]
        )

    async_add_new_orders()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_orders))


class WoltOrderSensor(CoordinatorEntity[WoltDataUpdateCoordinator], SensorEntity):
    """Representation of a Wolt order sensor."""

    _attr_attribution = "Data provided by Wolt"

    _attr_icon = "mdi:package-variant"

    def __init__(
        self,
        coordinator: WoltDataUpdateCoordinator,
        order_id: str,
        name: str,
    ) -> None:
        super().__init__(coordinator)
        self.order_id = order_id
        self._attr_name = name
        self._attr_unique_id = f"wolt_{order_id}"

    @property
    def available(self) -> bool:
        """Remain available while the order exists in the shared snapshot."""
        return super().available and self.order_id in self.coordinator.data.orders

    @property
    def _order_data(self) -> dict[str, Any]:
        """Merge the order summary with richer active tracking details."""
        return {
            **self.coordinator.data.orders.get(self.order_id, {}),
            **self.coordinator.data.details.get(self.order_id, {}),
        }

    @property
    def native_value(self):
        """Return the normalized Wolt status as a scalar sensor state."""
        order = self._order_data
        status = order.get("status")
        if isinstance(status, dict):
            status = status.get("value") or status.get("text") or status.get("label")
        if status is None:
            telemetry = order.get("telemetry")
            status = (
                telemetry.get("order_status_type")
                if isinstance(telemetry, dict)
                else order.get("order_status_type")
            )
        return str(status) if status is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return useful, non-credential order metadata from the shared snapshot."""
        order = self._order_data
        items = order.get("items")
        return {
            "delivery_eta": order.get("delivery_eta"),
            "client_pre_estimate": order.get("client_pre_estimate"),
            "venue_name": order.get("venue_name"),
            "payment_amount": order.get("payment_amount"),
            "items": [item.get("name") for item in items if isinstance(item, dict)]
            if isinstance(items, list)
            else [],
        }


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
            _LOGGER.warning("Unable to update a configured Wolt venue: %s", err)
            return
        if not details:
            self._attr_available = False
            _LOGGER.warning("Configured Wolt venue details were not found")
            return

        venue = details.get("venue") or details.get("venue_info") or {}
        self._attr_available = True
        open_info = venue.get("delivery_open_status") or venue.get("open_status") or {}

        is_open = open_info.get("is_open")
        if is_open is None:
            is_open = venue.get("online")
        if is_open is None:
            is_open = venue.get("is_open")
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
