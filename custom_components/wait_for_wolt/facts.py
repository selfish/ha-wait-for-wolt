"""Strict scalar projections of observed Wolt purchase payloads."""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any

# Explicit ISO minor-unit exponents; unknown currencies stay unknown.
_EXPONENTS: dict[str, int] = dict.fromkeys(
    [
        "ILS",
        "EUR",
        "USD",
        "GBP",
        "CAD",
        "AUD",
        "CHF",
        "NOK",
        "SEK",
        "DKK",
        "PLN",
        "CZK",
        "RON",
        "HUF",
        "BGN",
        "GEL",
        "RSD",
        "UAH",
    ],
    2,
)
_EXPONENTS.update(JPY=0, KRW=0, BHD=3, KWD=3, OMR=3, TND=3)


def money(data: dict[str, Any], key: str) -> tuple[Decimal | None, str | None]:
    """Read integer minor units with an explicit, recognized currency."""
    currency = data.get("currency")
    amount = data.get(key)
    if not isinstance(currency, str) or currency not in _EXPONENTS:
        return None, None
    if type(amount) is not int or amount < 0:
        return None, currency
    return Decimal(amount).scaleb(-_EXPONENTS[currency]), currency


def summary_total(order: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    """Use only observed unambiguous currency formats, cross-checking telemetry."""
    text = order.get("total")
    if not isinstance(text, str):
        return None, None
    match = re.fullmatch(r"([₪€])([0-9]+(?:,[0-9]{3})*\.[0-9]{2})", text)
    if match is None:
        return None, None
    currency = {"₪": "ILS", "€": "EUR"}[match[1]]
    telemetry = order.get("telemetry")
    amount = telemetry.get("end_amount") if isinstance(telemetry, dict) else None
    value, currency = money({"currency": currency, "amount": amount}, "amount")
    if value != Decimal(match[2].replace(",", "")):
        return None, currency
    return value, currency


def item_count(order: dict[str, Any]) -> int | None:
    """Sum product quantities, never modifiers or guessed line-item counts."""
    items = order.get("items")
    if not isinstance(items, list):
        return None
    if any(
        not isinstance(item, dict)
        or type(item.get("count")) is not int
        or item["count"] < 0
        for item in items
    ):
        return None
    return sum(item["count"] for item in items)


def dropoff_coordinates(details: dict[str, Any]) -> tuple[float, float] | None:
    """Read the actual GeoJSON destination; never substitute HA's home zone."""
    location = details.get("delivery_location")
    point = location.get("coordinates") if isinstance(location, dict) else None
    if not isinstance(point, dict) or point.get("type") != "Point":
        return None
    coordinates = point.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) != 2:
        return None
    lon, lat = coordinates
    if any(type(x) not in (float, int) or not math.isfinite(x) for x in (lat, lon)):
        return None
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    return float(lat), float(lon)
