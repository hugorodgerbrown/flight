"""The Share model: a live link to one leg of a flight, which anyone with it can open.

A share belongs to the signed-in person who made it, and follows the leg
Flightradar24 was tracking then (``fr24_id``), never the flight number: BA117
flies every day, and yesterday's link must not show today's flight. It keeps
the leg's latest card (``snapshot``), so a link still shows the route and how
it ended once Flightradar24 has moved on. It ends a day after landing, and is
deleted then (by the watch_flights cron) or when its maker stops it, as the
privacy notice says.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import BaseModel

# A link lasts this long after its leg lands...
KEEP_AFTER_LANDING = timedelta(hours=24)
# ...or this long after it was made, if no landing is ever seen.
KEEP_UNLANDED = timedelta(hours=48)


def new_token() -> str:
    """Return a link's secret: 128 random bits, URL-safe (22 characters)."""
    return secrets.token_urlsafe(16)


class ShareQuerySet(models.QuerySet["Share"]):
    """Queries over shares."""

    def for_user(self, user: object) -> ShareQuerySet:
        """Return ``user``'s shares."""
        return self.filter(user=user)

    def live(self, now: datetime | None = None) -> ShareQuerySet:
        """Return shares whose link still works."""
        return self.filter(expires_at__gt=now or timezone.now())

    def finished(self, now: datetime | None = None) -> ShareQuerySet:
        """Return shares whose link has ended, to delete."""
        return self.filter(expires_at__lte=now or timezone.now())


class Share(BaseModel):
    """A live link to one leg of a flight, made by a signed-in person."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shares"
    )
    # The link's secret, in its address: /f/<token>/.
    token = models.CharField(max_length=32, unique=True, default=new_token, editable=False)
    # The number as asked, upper case and without spaces (BA117, BAW17R).
    flight = models.CharField(max_length=10)
    # Flightradar24's id for the leg the link follows.
    fr24_id = models.CharField(max_length=20)
    # The leg's latest card, as the page draws it (shares.card).
    snapshot = models.JSONField(default=dict)
    landed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    objects = ShareQuerySet.as_manager()

    class Meta:
        """Model metadata."""

        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "fr24_id"])]

    def to_string(self) -> str:
        """Return the flight and its route, such as "BA117 LHR-JFK"."""
        origin = (self.snapshot.get("origin") or {}).get("code")
        destination = (self.snapshot.get("destination") or {}).get("code")
        route = f" {origin}-{destination}" if origin and destination else ""
        return f"{self.flight}{route}"

    def is_live(self, now: datetime | None = None) -> bool:
        """Return whether the link still works."""
        return self.expires_at > (now or timezone.now())

    def landed(self, moment: datetime) -> None:
        """Record the leg's landing at ``moment``; the link lasts a day from then."""
        self.landed_at = moment
        self.expires_at = moment + KEEP_AFTER_LANDING
