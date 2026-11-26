"""Tests for the Airport model and its admin."""

from typing import Any

import pytest
from django.test import Client

from apps.flights.models import Airport
from tests.factories import AirportFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_the_bundled_airports_are_loaded() -> None:
    """The migration loads every airport with an IATA code, with its place and time zone."""
    assert Airport.objects.count() > 7000
    heathrow = Airport.objects.with_code("LHR").get()
    assert (heathrow.icao, heathrow.name, heathrow.tz) == (
        "EGLL",
        "London Heathrow Airport",
        "Europe/London",
    )


def test_an_airport_is_found_by_either_code() -> None:
    """IATA or ICAO, any case, find the same airport."""
    quayside = AirportFactory.create()
    assert Airport.objects.with_code("qqq").get() == quayside
    assert Airport.objects.with_code("QQQQ").get() == quayside
    assert not Airport.objects.with_code("QXA").exists()


def test_an_airport_reads_as_travellers_know_it() -> None:
    """The IATA code where there is one, else ICAO."""
    quayside = AirportFactory.create()
    assert quayside.to_string() == "Quayside Airport (QQQ)"
    assert str(quayside) == "Quayside Airport (QQQ)"
    strip = AirportFactory.create(iata="", icao="QQXX", name="An airstrip")
    assert strip.code == "QQXX"
    assert quayside.as_place() == {
        "code": "QQQ",
        "name": "Quayside Airport",
        "lat": 50.5,
        "lon": -1.5,
        "tz": "Europe/London",
    }


def test_airports_are_ordered_by_icao() -> None:
    """The admin's list reads in code order."""
    codes = list(Airport.objects.values_list("icao", flat=True)[:50])
    assert codes == sorted(codes)


def test_staff_can_list_airports(client: Client, db: Any) -> None:
    """The admin lists airports and searches them."""
    client.force_login(UserFactory.create(is_staff=True, is_superuser=True))
    response = client.get("/admin/flights/airport/", {"q": "heathrow"})
    assert response.status_code == 200
    assert b"London Heathrow Airport (LHR)" in response.content
