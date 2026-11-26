"""The Airport model: an airport Flightradar24 named, kept so it's fetched only once."""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class AirportQuerySet(models.QuerySet["Airport"]):
    """Queries over airports."""

    def with_code(self, code: str) -> AirportQuerySet:
        """Return the airport with this IATA or ICAO code (codes are upper case)."""
        code = code.upper()
        return self.filter(Q(iata=code) | Q(icao=code))


class Airport(BaseModel):
    """An airport, as Flightradar24 describes it.

    Flightradar24's flights name airports only by code, so the name, place
    and time zone come from its airport endpoint, once per airport.
    """

    iata = models.CharField(max_length=3, blank=True, db_index=True)
    icao = models.CharField(max_length=4, unique=True)
    name = models.CharField(max_length=200)
    city = models.CharField(max_length=200, blank=True)
    country = models.CharField(max_length=200, blank=True)
    lat = models.FloatField()
    lon = models.FloatField()
    # An IANA time zone name, such as Europe/London.
    tz = models.CharField(max_length=64)

    objects = AirportQuerySet.as_manager()

    class Meta(BaseModel.Meta):
        """Model metadata."""

        ordering = ["icao"]

    def to_string(self) -> str:
        """Return the airport as "London Heathrow (LHR)"."""
        return f"{self.name} ({self.code})"

    @property
    def code(self) -> str:
        """Return the code travellers know: IATA where there is one, else ICAO."""
        return self.iata or self.icao

    def as_place(self) -> dict[str, object]:
        """Return the airport as a lookup's answer and the map card name it."""
        return {
            "code": self.code,
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "tz": self.tz,
        }
