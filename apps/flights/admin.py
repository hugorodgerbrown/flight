"""Admin for airports."""

from django.contrib import admin

from apps.flights.models import Airport


@admin.register(Airport)
class AirportAdmin(admin.ModelAdmin):
    """Airports Flightradar24 has named, by ICAO code."""

    list_display = ("to_string", "icao", "city", "country", "tz", "created_at")
    search_fields = ("iata", "icao", "name", "city")
