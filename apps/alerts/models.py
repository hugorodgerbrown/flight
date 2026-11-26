"""Followed flights and the push subscriptions their alerts go to (RAS-144).

A ``Follow`` is one person following one leg of a flight number: the next
leg to take off after they followed it, or the one in the air when they
did. The watcher (``watch.py``) binds it to Flightradar24's leg id once
that leg shows up, records when it took off and landed, and records when
each alert went, so no alert is sent twice.

A ``PushSubscription`` is one browser that said yes to notifications.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import BaseModel

# A follow whose flight never takes off gives up after this long.
WAIT_FOR_TAKE_OFF = timedelta(hours=24)
# A landed flight stays on the list this long, then clears.
KEEP_LANDED = timedelta(hours=24)
# A flight in the air that's never reported landed gives up this long after take-off.
WAIT_FOR_LANDING = timedelta(hours=20)


class FollowQuerySet(models.QuerySet["Follow"]):
    """Queries over follows."""

    def for_user(self, user: object) -> FollowQuerySet:
        """Return ``user``'s follows."""
        return self.filter(user=user)

    def active(self) -> FollowQuerySet:
        """Return follows still waiting on a take-off or a landing."""
        return self.filter(landed_at__isnull=True, ended_at__isnull=True)

    def due(self, now: datetime | None = None) -> FollowQuerySet:
        """Return active follows whose next check has come."""
        moment = now or timezone.now()
        return self.active().filter(Q(next_check_at__isnull=True) | Q(next_check_at__lte=moment))

    def shown(self, now: datetime | None = None) -> FollowQuerySet:
        """Return the follows the Following list shows: active, or finished in the last day."""
        moment = now or timezone.now()
        cutoff = moment - KEEP_LANDED
        return self.filter(
            Q(landed_at__isnull=True, ended_at__isnull=True)
            | Q(landed_at__gt=cutoff)
            | Q(ended_at__gt=cutoff)
        )

    def cleared(self, now: datetime | None = None) -> FollowQuerySet:
        """Return follows finished more than a day ago, safe to delete."""
        moment = now or timezone.now()
        cutoff = moment - KEEP_LANDED
        return self.filter(Q(landed_at__lte=cutoff) | Q(ended_at__lte=cutoff))


class Follow(BaseModel):
    """One person following one leg of a flight number, for its take-off and landing alerts."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="follows"
    )
    # The number as typed, upper case and without spaces (BA117, BAW17R).
    flight = models.CharField(max_length=10)
    push = models.BooleanField(default=True)
    email = models.BooleanField(default=True)
    # Only a leg that takes off at or after this is the one followed (the
    # follow's time, or a landing seen when it was made).
    not_before = models.DateTimeField()
    # Flightradar24's id for the leg, once it's seen.
    fr24_id = models.CharField(max_length=20, blank=True)
    # The route as Flightradar24 gives it: IATA codes, else ICAO.
    origin = models.CharField(max_length=4, blank=True)
    destination = models.CharField(max_length=4, blank=True)
    aircraft = models.CharField(max_length=10, blank=True)
    took_off_at = models.DateTimeField(null=True, blank=True)
    arrives_at = models.DateTimeField(null=True, blank=True)
    landed_at = models.DateTimeField(null=True, blank=True)
    took_off_sent_at = models.DateTimeField(null=True, blank=True)
    landed_sent_at = models.DateTimeField(null=True, blank=True)
    # Set when the watcher gives up: it never took off, or was never reported landed.
    ended_at = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(null=True, blank=True)

    objects = FollowQuerySet.as_manager()

    class Meta:
        """Model metadata."""

        ordering = ["-created_at"]
        indexes = [models.Index(fields=["landed_at", "ended_at", "next_check_at"])]

    def to_string(self) -> str:
        """Return the flight and its route, such as "BA117 LHR-JFK"."""
        route = f" {self.origin}-{self.destination}" if self.origin else ""
        return f"{self.flight}{route}"

    @property
    def state(self) -> str:
        """Return "waiting", "airborne", "landed" or "ended"."""
        if self.landed_at:
            return "landed"
        if self.ended_at:
            return "ended"
        if self.took_off_at:
            return "airborne"
        return "waiting"

    def progress(self, now: datetime | None = None) -> float | None:
        """Return how far through its flight time it is (0 to 1), from the clock, or None."""
        if not (self.took_off_at and self.arrives_at) or self.landed_at:
            return None
        moment = now or timezone.now()
        total = (self.arrives_at - self.took_off_at).total_seconds()
        if total <= 0:
            return None
        done = (moment - self.took_off_at).total_seconds()
        return round(min(1.0, max(0.0, done / total)), 3)


class PushSubscriptionQuerySet(models.QuerySet["PushSubscription"]):
    """Queries over push subscriptions."""

    def for_user(self, user: object) -> PushSubscriptionQuerySet:
        """Return ``user``'s push subscriptions."""
        return self.filter(user=user)


class PushSubscription(BaseModel):
    """One browser that agreed to get Flight's notifications (a Web Push subscription)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions"
    )
    # The push service's address for this browser: unique, and the key for updates.
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    # A short name for the browser, from its User-Agent ("Safari on iPhone").
    device = models.CharField(max_length=100, blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)

    objects = PushSubscriptionQuerySet.as_manager()

    class Meta:
        """Model metadata."""

        ordering = ["-created_at"]

    def to_string(self) -> str:
        """Return the browser, such as "Safari on iPhone"."""
        return self.device or "A browser"

    def as_info(self) -> dict[str, object]:
        """Return the subscription as pywebpush takes it."""
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}
