"""Public Wolt venue-page metadata helpers.

The consumer venue endpoint exposes availability and delivery polygons, but the
public venue webpage also embeds a schema.org Restaurant object containing the
canonical address and exact venue coordinates.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any

WOLT_VENUE_PAGE_URL = "https://wolt.com/{language}/{country}/{city}/restaurant/{slug}"


class _JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capturing = False
        self._parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        values = {key.lower(): (value or "") for key, value in attrs}
        if values.get("type", "").lower() == "application/ld+json":
            self._capturing = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._capturing:
            self.blocks.append("".join(self._parts))
            self._capturing = False
            self._parts = []


def slugify_city(value: Any) -> str:
    """Convert Wolt's display city into the URL path form used by venue pages."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def venue_slug(order: dict[str, Any]) -> str | None:
    venue = order.get("venue") if isinstance(order.get("venue"), dict) else {}
    value = venue.get("slug") or order.get("venue_slug")
    return str(value).strip().strip("/") if value else None


def build_venue_page_url(order: dict[str, Any]) -> str | None:
    """Build the public Wolt venue URL from the orders-page venue metadata."""
    venue = order.get("venue") if isinstance(order.get("venue"), dict) else {}
    slug = venue_slug(order)
    city = slugify_city(venue.get("city") or order.get("city"))
    country = slugify_city(venue.get("country") or order.get("country"))
    language = slugify_city(venue.get("language") or order.get("language") or "en")
    if not slug or not city or not country:
        return None
    return WOLT_VENUE_PAGE_URL.format(
        language=language or "en",
        country=country,
        city=city,
        slug=slug,
    )


def _iter_json_ld_objects(value: Any):
    if isinstance(value, list):
        for item in value:
            yield from _iter_json_ld_objects(item)
        return
    if not isinstance(value, dict):
        return
    yield value
    graph = value.get("@graph")
    if isinstance(graph, (list, dict)):
        yield from _iter_json_ld_objects(graph)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except TypeError, ValueError, OverflowError:
        return None
    return number if math.isfinite(number) else None


def parse_venue_page(
    html: str, expected_name: str | None = None
) -> dict[str, Any] | None:
    """Extract a venue address and coordinates from Wolt's JSON-LD metadata."""
    parser = _JsonLdParser()
    parser.feed(html)
    candidates: list[dict[str, Any]] = []
    for block in parser.blocks:
        try:
            decoded = json.loads(block)
        except TypeError, ValueError, json.JSONDecodeError:
            continue
        for item in _iter_json_ld_objects(decoded):
            kind = item.get("@type")
            kinds = (
                {str(value) for value in kind}
                if isinstance(kind, list)
                else {str(kind)}
            )
            if not kinds.intersection(
                {"Restaurant", "FoodEstablishment", "LocalBusiness"}
            ):
                continue
            geo = item.get("geo") if isinstance(item.get("geo"), dict) else {}
            latitude = _number(geo.get("latitude"))
            longitude = _number(geo.get("longitude"))
            if (
                latitude is None
                or longitude is None
                or not -90 <= latitude <= 90
                or not -180 <= longitude <= 180
            ):
                continue
            address = item.get("address")
            address_data = address if isinstance(address, dict) else {}
            street = address_data.get("streetAddress") if address_data else address
            candidates.append(
                {
                    "venue_name": item.get("name"),
                    "venue_address": street,
                    "venue_address_locality": address_data.get("addressLocality"),
                    "venue_postal_code": address_data.get("postalCode"),
                    "venue_country": address_data.get("addressCountry"),
                    "venue_latitude": latitude,
                    "venue_longitude": longitude,
                }
            )
    if not candidates:
        return None
    if expected_name:
        expected = re.sub(r"\s+", " ", expected_name).strip().casefold()
        for candidate in candidates:
            actual = (
                re.sub(r"\s+", " ", str(candidate.get("venue_name") or ""))
                .strip()
                .casefold()
            )
            if actual == expected:
                return {
                    key: value
                    for key, value in candidate.items()
                    if value not in (None, "")
                }
    return {
        key: value for key, value in candidates[0].items() if value not in (None, "")
    }
