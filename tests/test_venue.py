"""Adversarial public venue metadata; all values are synthetic."""

import json

import pytest

from custom_components.wait_for_wolt.venue import parse_venue_page


def page(latitude, longitude):
    return (
        '<script type="application/ld+json">'
        + json.dumps(
            {
                "@type": "Restaurant",
                "name": "Synthetic venue",
                "geo": {"latitude": latitude, "longitude": longitude},
            }
        )
        + "</script>"
    )


@pytest.mark.parametrize(
    "latitude,longitude",
    [
        (True, 20),
        (20, False),
        (float("nan"), 20),
        (20, float("nan")),
        (float("inf"), 20),
        (20, float("-inf")),
        ("NaN", 20),
        (20, "Infinity"),
        (90.1, 20),
        (-90.1, 20),
        (20, 180.1),
        (20, -180.1),
        (None, 20),
        (20, {}),
        ([], 20),
        ("unknown", 20),
        (10**400, 20),
    ],
)
def test_invalid_coordinates_are_not_published(latitude, longitude):
    assert parse_venue_page(page(latitude, longitude)) is None


@pytest.mark.parametrize(
    "latitude,longitude", [(0, 0), (90, 180), (-90, -180), ("20.5", "30.5")]
)
def test_valid_coordinate_boundaries_and_numeric_strings(latitude, longitude):
    result = parse_venue_page(page(latitude, longitude))
    assert result is not None
    assert result["venue_latitude"] == float(latitude)
    assert result["venue_longitude"] == float(longitude)
