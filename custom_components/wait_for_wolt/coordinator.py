"""Coordinator for conservative Wolt order polling."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    WoltApi,
    WoltAuthenticationError,
    WoltConnectionError,
    WoltInvalidPayloadError,
    WoltRateLimitError,
    is_active_order,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ACTIVE_UPDATE_INTERVAL = timedelta(seconds=30)
IDLE_UPDATE_INTERVAL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class WoltCoordinatorData:
    """One coherent snapshot of account orders and active-order details."""

    orders: dict[str, dict[str, Any]]
    active_order_ids: frozenset[str]
    details: dict[str, dict[str, Any]]


class WoltDataUpdateCoordinator(DataUpdateCoordinator[WoltCoordinatorData]):
    """Fetch each authenticated Wolt resource once per polling cycle."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: WoltApi,
    ) -> None:
        """Initialize the coordinator at the conservative idle interval."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=IDLE_UPDATE_INTERVAL,
        )
        self.api = api
        self._rich_tracking_warning_logged = False

    async def _async_update_data(self) -> WoltCoordinatorData:
        """Fetch orders and details, translating failures for Home Assistant."""
        try:
            raw_orders = await self.api.fetch_orders()
            orders = {
                order_id: order
                for order in raw_orders
                if (order_id := self.order_id(order)) is not None
            }
            active_order_ids = frozenset(
                order_id for order_id, order in orders.items() if is_active_order(order)
            )
            details: dict[str, dict[str, Any]] = {}
            rich_tracking_failed = False
            # Orders are normally singular. Keep requests sequential to avoid bursts
            # against Wolt's unofficial consumer endpoints.
            for order_id in sorted(active_order_ids):
                try:
                    details[order_id] = await self.api.fetch_order_details(order_id)
                except WoltAuthenticationError, WoltRateLimitError:
                    raise
                except WoltConnectionError, WoltInvalidPayloadError:
                    # The summary remains useful while the optional rich endpoint
                    # is unavailable or has not populated a newly placed order.
                    rich_tracking_failed = True
            if rich_tracking_failed and not self._rich_tracking_warning_logged:
                _LOGGER.warning("Rich Wolt order tracking details are unavailable")
            self._rich_tracking_warning_logged = rich_tracking_failed
        except WoltAuthenticationError as err:
            raise ConfigEntryAuthFailed("Wolt authentication failed") from err
        except WoltRateLimitError as err:
            raise UpdateFailed("Wolt rate limit reached") from err
        except (WoltConnectionError, WoltInvalidPayloadError) as err:
            raise UpdateFailed("Unable to update Wolt orders") from err

        self.update_interval = (
            ACTIVE_UPDATE_INTERVAL if active_order_ids else IDLE_UPDATE_INTERVAL
        )
        return WoltCoordinatorData(orders, active_order_ids, details)

    @staticmethod
    def order_id(order: dict[str, Any]) -> str | None:
        """Return Wolt's current purchase ID with legacy fallbacks."""
        value = order.get("purchase_id") or order.get("order_id") or order.get("id")
        return str(value) if value else None


@dataclass(slots=True)
class WoltRuntimeData:
    """Runtime objects owned by one Wolt config entry."""

    api: WoltApi
    coordinator: WoltDataUpdateCoordinator
