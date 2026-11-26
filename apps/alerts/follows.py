"""Following and unfollowing a flight: the service the views and MCP tools share (RAS-144).

``follow`` saves a follow and asks Flightradar24 (through the cached
``lookup.where``) whether the flight is already in the air, so the list can
show its route at once. A flight in the air when it's followed is that
follow's leg, and only its landing alert is left. Otherwise the watcher
binds the next leg to take off.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.alerts.models import Follow
from apps.flights import lookup

logger = logging.getLogger(__name__)

# The flight numbers where_is takes, plus callsigns (BAW17R): operating numbers only.
FLIGHT_NUMBER = re.compile(r"^(?:[A-Z]{2}|[A-Z]\d|\d[A-Z])[A-Z]?\d{1,4}[A-Z]?$")


class NotAFlightNumber(ValueError):
    """The text isn't a flight number such as BA117."""


def clean_number(text: str) -> str:
    """Return ``text`` as a flight number (upper case, no spaces), or raise NotAFlightNumber."""
    number = re.sub(r"\s+", "", text).upper()
    if not FLIGHT_NUMBER.match(number):
        raise NotAFlightNumber(text)
    return number


def follow(user: Any, text: str, now: datetime | None = None) -> tuple[Follow, bool]:
    """Follow flight ``text`` for ``user``; return the follow and whether it's new.

    Following a flight that's already followed returns that follow, even when
    two requests race: the database keeps one active follow per flight.
    """
    number = clean_number(text)
    moment = now or timezone.now()
    existing = Follow.objects.for_user(user).active().filter(flight=number).first()
    if existing is not None:
        return existing, False
    item = Follow(
        user=user,
        flight=number,
        not_before=moment,
        email=bool(getattr(user, "email", "")),
    )
    prime(item)
    try:
        with transaction.atomic():
            item.save()
    except IntegrityError:
        # Another request followed it while this one looked it up.
        return Follow.objects.for_user(user).active().get(flight=number), False
    logger.info("alerts.follow user=%s flight=%s state=%s", user.pk, number, item.state)
    return item, True


def prime(item: Follow) -> None:
    """Fill in a new follow from a live lookup, if Flightradar24 has the flight in the air.

    A failed or empty lookup leaves the follow waiting: the watcher finds its
    leg when it takes off.
    """
    try:
        flight = lookup.where(item.flight)
    except lookup.NotConnected, lookup.Unavailable:
        logger.warning("alerts.follow %s: no lookup, waiting for take-off", item.flight)
        return
    if not flight or flight["status"] != lookup.AIRBORNE or not flight.get("fr24_id"):
        return
    item.fr24_id = flight["fr24_id"]
    item.origin = flight["origin"]["code"]
    item.destination = flight["destination"]["code"]
    item.aircraft = flight.get("aircraft") or ""
    item.took_off_at = parse(flight.get("departed")) or item.not_before
    item.arrives_at = parse(flight.get("arrives"))
    # It was in the air before it was followed: there's no take-off to tell anyone about.
    item.took_off_sent_at = item.not_before


def parse(value: str | None) -> datetime | None:
    """Return an ISO time from a lookup, or None."""
    return datetime.fromisoformat(value) if value else None


def unfollow(user: Any, text: str) -> int:
    """Stop following flight ``text`` for ``user``; return how many follows went."""
    number = clean_number(text)
    deleted, _ = Follow.objects.for_user(user).filter(flight=number).delete()
    logger.info("alerts.unfollow user=%s flight=%s deleted=%s", user.pk, number, deleted)
    return deleted
