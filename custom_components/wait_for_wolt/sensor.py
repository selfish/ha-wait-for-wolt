"""Sensor platform for Wolt order tracker."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

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

ORDER_STATUS_OPTIONS = [
    "pending",
    "preparing",
    "ready_for_pickup",
    "picked_up",
    "on_the_way",
    "arriving",
    "delivered",
    "cancelled",
    "failed",
    "unknown",
]

ORDER_STATUS_DESCRIPTION = SensorEntityDescription(
    key="status",
    translation_key="order_status",
    device_class=SensorDeviceClass.ENUM,
    options=ORDER_STATUS_OPTIONS,
)

ORDER_ETA_DESCRIPTION = SensorEntityDescription(
    key="eta",
    translation_key="order_eta",
    device_class=SensorDeviceClass.TIMESTAMP,
)


def _raw_status(order: dict[str, Any]) -> str | None:
    """Extract a scalar status while respecting authoritative telemetry."""
    status_type: Any = None
    if "telemetry" in order:
        telemetry = order["telemetry"]
        status_type = (
            telemetry.get("order_status_type") if isinstance(telemetry, dict) else None
        )
        if str(status_type).upper() != "IN_PROGRESS":
            return str(status_type) if status_type is not None else None
    elif "order_status_type" in order:
        status_type = order["order_status_type"]
        if str(status_type).upper() != "IN_PROGRESS":
            return str(status_type) if status_type is not None else None

    status = order.get("status")
    if isinstance(status, dict):
        status = status.get("value") or status.get("text") or status.get("label")
    if status is None:
        status = status_type
    if str(status_type).upper() == "IN_PROGRESS" and status is not None:
        display_status = re.sub(r"[^a-z0-9]+", "_", str(status).strip().lower()).strip(
            "_"
        )
        if any(
            token in display_status
            for token in (
                "delivered",
                "completed",
                "finished",
                "cancel",
                "fail",
                "reject",
                "refund",
            )
        ):
            return str(status_type)
    return str(status) if status is not None else None


def normalize_order_status(order: dict[str, Any]) -> str:
    """Map unstable Wolt status text to a fixed Home Assistant enum."""
    raw = _raw_status(order)
    if not raw:
        return "unknown"
    value = re.sub(r"[^a-z0-9]+", "_", raw.casefold()).strip("_")
    if any(token in value for token in ("cancel", "refunded")):
        return "cancelled"
    if any(token in value for token in ("fail", "reject", "declin")):
        return "failed"
    if any(token in value for token in ("delivered", "completed", "finished")):
        return "delivered"
    if any(token in value for token in ("arriv", "nearby", "almost_there")):
        return "arriving"
    if any(
        token in value
        for token in ("on_the_way", "en_route", "courier_delivery", "delivery")
    ):
        return "on_the_way"
    if any(token in value for token in ("picked_up", "courier_pickup")):
        return "picked_up"
    if any(token in value for token in ("ready", "awaiting_pickup")):
        return "ready_for_pickup"
    if any(token in value for token in ("prepar", "production", "restaurant")):
        return "preparing"
    if any(
        token in value
        for token in ("pending", "received", "created", "in_progress", "accepted")
    ):
        return "pending"
    return "unknown"


def _parse_eta(value: Any) -> datetime | None:
    """Parse an ETA without guessing from human-readable duration text."""
    if isinstance(value, bool):
        return None
    if isinstance(value, dict):
        for key in ("value", "timestamp", "max", "end"):
            if key in value and (parsed := _parse_eta(value[key])) is not None:
                return parsed
        return None
    if isinstance(value, int | float):
        timestamp = value / 1000 if value > 10_000_000_000 else value
        # Explicit ETAs must be plausible wall-clock timestamps. Small values
        # are durations/range bounds, not Unix timestamps.
        if not 1_577_836_800 <= timestamp <= 4_102_444_800:
            return None
        try:
            return datetime.fromtimestamp(timestamp, UTC)
        except OSError, OverflowError, ValueError:
            return None
    if not isinstance(value, str):
        return None
    parsed = dt_util.parse_datetime(value)
    return parsed if parsed is not None and parsed.tzinfo is not None else None


def extract_order_eta(order: dict[str, Any]) -> datetime | None:
    """Extract the first explicit timestamp-shaped ETA."""
    for key in ("delivery_eta", "estimated_delivery_time", "eta"):
        if (parsed := _parse_eta(order.get(key))) is not None:
            return parsed
    return None


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
        registry = er.async_get(hass)
        candidate_order_ids = set(coordinator.data.active_order_ids)
        for order_id in coordinator.data.orders:
            if any(
                _owned_registry_entity(
                    registry,
                    entry.entry_id,
                    unique_id,
                )
                is not None
                for unique_id in (
                    f"wolt_{order_id}",
                    _order_unique_id(entry.entry_id, order_id, "status"),
                    _order_unique_id(entry.entry_id, order_id, "eta"),
                )
            ):
                candidate_order_ids.add(order_id)

        new_order_ids = candidate_order_ids - known_order_ids
        if not new_order_ids:
            return
        known_order_ids.update(new_order_ids)
        entities: list[SensorEntity] = []
        for order_id in sorted(new_order_ids):
            status_unique_id = _order_unique_id(entry.entry_id, order_id, "status")
            legacy_entity = _owned_registry_entity(
                registry,
                entry.entry_id,
                f"wolt_{order_id}",
            )
            if (
                legacy_entity is not None
                and registry.async_get_entity_id("sensor", DOMAIN, status_unique_id)
                is None
            ):
                registry.async_update_entity(
                    legacy_entity.entity_id,
                    new_unique_id=status_unique_id,
                    translation_key="order_status",
                    has_entity_name=True,
                )
            entities.extend(
                (
                    WoltOrderStatusSensor(coordinator, entry.entry_id, order_id),
                    WoltOrderEtaSensor(coordinator, entry.entry_id, order_id),
                )
            )
        async_add_entities(entities)

    async_add_new_orders()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_orders))


def _owned_registry_entity(
    registry: er.EntityRegistry,
    entry_id: str,
    unique_id: str,
) -> er.RegistryEntry | None:
    """Return a sensor registry entity only when this config entry owns it."""
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    entity = registry.async_get(entity_id) if entity_id is not None else None
    return entity if entity is not None and entity.config_entry_id == entry_id else None


def _order_unique_id(entry_id: str, order_id: str, key: str) -> str:
    """Scope purchase entities to one config entry."""
    return f"{entry_id}_{order_id}_{key}"


class WoltOrderEntity(CoordinatorEntity[WoltDataUpdateCoordinator], SensorEntity):
    """Base for a privacy-safe Wolt order entity."""

    _attr_attribution = "Data provided by Wolt"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WoltDataUpdateCoordinator,
        entry_id: str,
        order_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.order_id = order_id
        self._entry_id = entry_id

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
    def device_info(self) -> DeviceInfo:
        """Group status and ETA under a stable per-purchase device."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry_id}:{self.order_id}")},
            manufacturer="Wolt",
            model="Delivery order",
            name="Wolt order",
        )


class WoltOrderStatusSensor(WoltOrderEntity):
    """Stable enum status for one Wolt purchase."""

    entity_description = ORDER_STATUS_DESCRIPTION
    _attr_icon = "mdi:package-variant"

    def __init__(
        self,
        coordinator: WoltDataUpdateCoordinator,
        entry_id: str,
        order_id: str,
    ) -> None:
        super().__init__(coordinator, entry_id, order_id)
        self._attr_unique_id = _order_unique_id(entry_id, order_id, "status")

    @property
    def native_value(self) -> str:
        """Return a fixed automation-safe enum value."""
        return normalize_order_status(self._order_data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Never persist order metadata or payload fragments as attributes."""
        return {}


class WoltOrderEtaSensor(WoltOrderEntity):
    """Typed ETA timestamp for one Wolt purchase."""

    entity_description = ORDER_ETA_DESCRIPTION
    _attr_icon = "mdi:clock-outline"

    def __init__(
        self,
        coordinator: WoltDataUpdateCoordinator,
        entry_id: str,
        order_id: str,
    ) -> None:
        super().__init__(coordinator, entry_id, order_id)
        self._attr_unique_id = _order_unique_id(entry_id, order_id, "eta")

    @property
    def native_value(self) -> datetime | None:
        """Return an aware timestamp or unknown when Wolt provides no explicit ETA."""
        return extract_order_eta(self._order_data)


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
