"""App config for apps.flights."""

from django.apps import AppConfig


class FlightsConfig(AppConfig):
    """Live flight data from Flightradar24, and the airports it names."""

    name = "apps.flights"
    label = "flights"
