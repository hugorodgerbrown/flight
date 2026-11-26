"""Tests for the Airport model and its admin."""

from typing import Any

import pytest
from django.test import Client

from apps.flights.models import Airport
from tests.factories import AirportFactory, UserFactory

pytestmark = pytest.mark.django_db


def test_an_airport_is_found_by_either_code() -> None:
    """IATA or ICAO, any case, find the same airport."""
    heathrow = AirportFactory.create()
    assert Airport.objects.with_code("lhr").get() == heathrow
    assert Airport.objects.with_code("EGLL").get() == heathrow
    assert not Airport.objects.with_code("JFK").exists()


def test_an_airport_reads_as_travellers_know_it() -> None:
    """The IATA code where there is one, else ICAO."""
    heathrow = AirportFactory.create()
    assert heathrow.to_string() == "London Heathrow (LHR)"
    assert str(heathrow) == "London Heathrow (LHR)"
    strip = AirportFactory.create(iata="", icao="EGXX", name="An airstrip")
    assert strip.code == "EGXX"
    assert heathrow.as_place() == {
        "code": "LHR",
        "name": "London Heathrow",
        "lat": 51.47,
        "lon": -0.4543,
        "tz": "Europe/London",
    }


def test_airports_are_ordered_by_icao() -> None:
    """The admin's list reads in code order."""
    AirportFactory.create(iata="JFK", icao="KJFK", name="JFK")
    AirportFactory.create()
    assert [a.icao for a in Airport.objects.all()] == ["EGLL", "KJFK"]


def test_staff_can_list_airports(client: Client, db: Any) -> None:
    """The admin lists airports and searches them."""
    AirportFactory.create()
    client.force_login(UserFactory.create(is_staff=True, is_superuser=True))
    response = client.get("/admin/flights/airport/", {"q": "heathrow"})
    assert response.status_code == 200
    assert b"London Heathrow (LHR)" in response.content
