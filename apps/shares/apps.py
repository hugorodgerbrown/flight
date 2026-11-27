"""App config for apps.shares."""

from django.apps import AppConfig


class SharesConfig(AppConfig):
    """Live share links to one leg of a flight (RAS-145)."""

    name = "apps.shares"
    label = "shares"
