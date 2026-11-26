"""App config for apps.alerts."""

from django.apps import AppConfig


class AlertsConfig(AppConfig):
    """Followed flights, and the take-off and landing alerts sent for them (RAS-144)."""

    name = "apps.alerts"
    label = "alerts"
