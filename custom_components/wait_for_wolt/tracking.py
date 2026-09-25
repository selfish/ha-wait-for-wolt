"""Opt-in, coordinator-backed compatibility for existing arrival automations.

Never publish raw orders, addresses, items, driver identities or payments.
Coordinates are intentionally sensitive and require the maps option (or an
existing legacy map installation); diagnostics never include these snapshots.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import WoltDataUpdateCoordinator
from .privacy import location_allowed


def tracking_enabled(entry: ConfigEntry) -> bool:
    """An explicit user option always takes precedence over legacy migration."""
    return (
        entry.options.get("tracking_maps", entry.data.get("tracking_maps", False))
        is True
    )


def coordinates(lat: Any, lon: Any) -> dict[str, float]:
    """Reject malformed, nonfinite, and out-of-range positions."""
    if isinstance(lat, bool) or isinstance(lon, bool):
        return {}
    try:
        latitude, longitude = float(lat), float(lon)
    except TypeError, ValueError, OverflowError:
        return {}
    if not (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        return {}
    return {"latitude": latitude, "longitude": longitude}


def driver_fields(details: dict[str, Any]) -> dict[str, Any]:
    """Select the assigned driver, never an arbitrary other delivery driver."""
    drivers = details.get("_drivers")
    if not isinstance(drivers, list):
        return {}
    valid = [driver for driver in drivers if isinstance(driver, dict)]
    driver = next(
        (driver for driver in valid if driver.get("delivering_your_order") is True),
        None,
    )
    if (
        driver is None
        and len(valid) == 1
        and valid[0].get("delivering_your_order") is not False
    ):
        driver = valid[0]
    if driver is None:
        return {}
    out: dict[str, Any] = {}
    loc = driver.get("location")
    if isinstance(loc, list) and len(loc) == 2:
        out.update(coordinates(loc[1], loc[0]))
    if isinstance(driver.get("delivering_your_order"), bool):
        out["delivering_your_order"] = driver["delivering_your_order"]
    # ETA is parsed before entity publication; never expose its raw envelope.
    out["delivery_eta"] = driver.get("delivery_eta")
    heading = driver.get("heading")
    if (
        isinstance(heading, (int, float))
        and not isinstance(heading, bool)
        and math.isfinite(heading)
        and 0 <= heading <= 360
    ):
        out["courier_heading"] = heading
    return out


class WoltTrackingSensor(CoordinatorEntity[WoltDataUpdateCoordinator], SensorEntity):
    """One stable duration or route-marker entity for a purchase."""

    _attr_has_entity_name = False
    _attr_attribution = "Data provided by Wolt"

    def __init__(
        self,
        coordinator: WoltDataUpdateCoordinator,
        entry_id: str,
        order_id: str,
        kind: str,
        allow_location: bool = False,
    ) -> None:
        super().__init__(coordinator)
        self.order_id = order_id
        self.kind = kind
        self.allow_location = allow_location
        self._attr_unique_id = f"{entry_id}_{order_id}_{kind}"
        # Prefixes are a public compatibility contract used by existing cards.
        self._attr_name = f"Wolt {kind} order"
        self._attr_icon = {
            "delivery": "mdi:moped",
            "pickup": "mdi:store-marker",
            "destination": "mdi:home-map-marker",
        }[kind]
        if kind == "delivery":
            self._attr_device_class = SensorDeviceClass.DURATION
            self._attr_native_unit_of_measurement = UnitOfTime.MINUTES

    @property
    def active(self) -> bool:
        return self.order_id in self.coordinator.data.active_order_ids

    @property
    def available(self) -> bool:
        return super().available and self.order_id in self.coordinator.data.orders

    def _attributes(self) -> dict[str, Any]:
        from .sensor import extract_order_eta, normalize_order_status

        summary = self.coordinator.data.orders.get(self.order_id, {})
        details = (
            self.coordinator.data.details.get(self.order_id, {}) if self.active else {}
        )
        order = {**details, **summary}
        # The order list owns the terminal-state discriminator.
        telemetry = summary.get("telemetry")
        status_type = (
            telemetry.get("order_status_type")
            if isinstance(telemetry, dict)
            else summary.get("order_status_type")
        )
        status_type = (
            "IN_PROGRESS"
            if self.active
            else (
                status_type.upper()
                if isinstance(status_type, str)
                and status_type.upper()
                in {
                    "DELIVERED",
                    "CANCELLED",
                    "FAILED",
                    "REJECTED",
                    "REFUNDED",
                    "COMPLETED",
                }
                else "UNKNOWN"
            )
        )
        attrs: dict[str, Any] = {
            "order_status_type": status_type,
            "order_status": normalize_order_status(order),
            "is_arriving_soon": False,
        }
        if self.kind != "delivery":
            attrs.update(route_point_type=self.kind, coordinate_source="unavailable")
        if not self.active:
            return attrs  # Never leave stale coordinates/arrival flags on completion.
        if self.kind != "delivery":
            if not self.allow_location:
                return attrs
            if self.kind == "pickup":
                location = self.coordinator.data.pickups.get(self.order_id, {})
                attrs.update(
                    coordinates(location.get("latitude"), location.get("longitude"))
                )
                if "latitude" in attrs:
                    attrs["coordinate_source"] = "wolt_venue_json_ld"
            else:
                # A home reference is an explicit convenience, not a Wolt dropoff.
                attrs["coordinate_source"] = "unavailable"
                if self.coordinator.entry.options.get("destination_home") is True:
                    home = self.hass.states.get("zone.home")
                    if home is not None:
                        coords = coordinates(
                            home.attributes.get("latitude"),
                            home.attributes.get("longitude"),
                        )
                        attrs.update(coords)
                        if coords:
                            attrs["coordinate_source"] = "home_reference"
            attrs["route_point_type"] = self.kind
            return attrs
        driver = driver_fields(details)
        eta = extract_order_eta(driver) or extract_order_eta(order)
        # A past estimate is not proof of imminent arrival. Keep it visible but
        # never let a stale zero-minute value trigger door/arrival automations.
        if eta is not None:
            remaining = eta - dt_util.utcnow()
            if -timedelta(minutes=1) <= remaining <= timedelta(hours=6):
                minutes = max(0, math.ceil(remaining.total_seconds() / 60))
                attrs.update(
                    delivery_eta=eta.isoformat(),
                    minutes_to_arrival=minutes,
                    is_arriving_soon=0 <= remaining.total_seconds() <= 180,
                )
        attrs.update(
            {
                key: value
                for key, value in driver.items()
                if key != "delivery_eta"
                and (
                    self.allow_location
                    or key not in {"latitude", "longitude", "courier_heading"}
                )
            }
        )
        event = details.get("tracking_event_type")
        if isinstance(event, str) and event in {
            "purchase_tracking",
            "dropoff_arrival",
            "dropoff_started",
        }:
            attrs["tracking_event_type"] = event
        return attrs

    @property
    def native_value(self) -> int | str | None:
        if self.kind == "delivery":
            return self._attributes().get("minutes_to_arrival")
        return self.kind if self.active else "inactive"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attributes()


@callback
def async_setup_tracking(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Migrate owned legacy identities and discover new orders without polling."""
    coordinator = entry.runtime_data.coordinator
    known: set[tuple[str, str]] = set()
    registry = er.async_get(hass)

    @callback
    def discover() -> None:
        entities: list[SensorEntity] = []
        order_ids = set(coordinator.data.orders)
        for item in er.async_entries_for_config_entry(registry, entry.entry_id):
            if item.platform != DOMAIN or item.domain != "sensor":
                continue
            uid = item.unique_id
            if uid in {
                "wolt_monthly_spend",
                f"{entry.entry_id}_monthly_spend_delivery",
            }:
                continue
            for kind in ("delivery", "pickup", "destination"):
                prefix, suffix = f"{entry.entry_id}_", f"_{kind}"
                if uid.startswith(prefix) and uid.endswith(suffix):
                    order_ids.add(uid[len(prefix) : -len(suffix)])
            for prefix in ("wolt_pickup_", "wolt_destination_", "wolt_"):
                if uid.startswith(prefix) and not uid.startswith("wolt_venue_"):
                    order_ids.add(uid[len(prefix) :])
                    break
        for order_id in sorted(order_ids):
            for kind in ("delivery", "pickup", "destination"):
                if (order_id, kind) in known:
                    continue
                uid = f"{entry.entry_id}_{order_id}_{kind}"
                legacy_uid = (
                    f"wolt_{order_id}"
                    if kind == "delivery"
                    else f"wolt_{kind}_{order_id}"
                )

                def owned(unique_id):
                    entity_id = registry.async_get_entity_id(
                        "sensor", DOMAIN, unique_id
                    )
                    item = registry.async_get(entity_id) if entity_id else None
                    return (
                        item
                        if item and item.config_entry_id == entry.entry_id
                        else None
                    )

                old, current = owned(legacy_uid), owned(uid)
                active = order_id in coordinator.data.active_order_ids
                allowed = location_allowed(entry, order_id, kind)
                if not (old or current or (active and (kind == "delivery" or allowed))):
                    continue
                # Preserve both registry records if destination already exists.
                # Never steal another entry's identity or change disabled state.
                if old and registry.async_get_entity_id("sensor", DOMAIN, uid) is None:
                    registry.async_update_entity(old.entity_id, new_unique_id=uid)
                entity = WoltTrackingSensor(
                    coordinator, entry.entry_id, order_id, kind, allowed
                )
                known.add((order_id, kind))
                entities.append(entity)
                if old and current:
                    # An earlier partial upgrade created both IDs. Keep the legacy
                    # automation target alive too, without stealing either record.
                    alias = WoltTrackingSensor(
                        coordinator, entry.entry_id, order_id, kind, allowed
                    )
                    alias._attr_unique_id = legacy_uid
                    entities.append(alias)
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))
