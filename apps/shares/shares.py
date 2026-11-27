"""Making a share link, and what its page shows now: the service the views and MCP share (RAS-145).

``share`` makes (or returns) the signed-in person's link to the leg
Flightradar24 is tracking for a flight number. ``current`` says what a link
shows now. It asks ``lookup.where``, which caches for a minute, so every
viewer of every link to one flight shares one Flightradar24 lookup a minute.
Once the leg has landed, or the link has ended, it asks nothing at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.alerts.follows import clean_number
from apps.flights import lookup
from apps.flights.models import Airport
from apps.shares.models import KEEP_UNLANDED, Share

logger = logging.getLogger(__name__)

# What a link's page shows.
LIVE = "live"
LANDED = "landed"
ENDED = "ended"


class NothingToShare(Exception):
    """Flightradar24 isn't tracking a leg of this flight that a link could follow."""


@dataclass(frozen=True)
class Shown:
    """What a link shows now: its state and the card to draw."""

    state: str
    flight: dict[str, Any]


def share(user: Any, text: str, now: datetime | None = None) -> tuple[Share, bool]:
    """Return ``user``'s link to the leg of flight ``text`` now tracked, and whether it's new.

    Raises NotAFlightNumber for text that isn't a flight number, NothingToShare
    when there's no leg in the air or landed in the last day, and
    lookup.NotConnected or lookup.Unavailable when Flightradar24 can't say.
    """
    number = clean_number(text)
    moment = now or timezone.now()
    flight = lookup.where(number)
    if flight is None or flight["status"] == lookup.LOST or not flight.get("fr24_id"):
        raise NothingToShare(number)
    with transaction.atomic():
        existing = (
            Share.objects.for_user(user)
            .live(moment)
            .filter(fr24_id=flight["fr24_id"])
            .select_for_update()
            .first()
        )
        if existing is not None:
            return existing, False
        item = Share(
            user=user,
            flight=number,
            fr24_id=flight["fr24_id"],
            snapshot=card(flight),
            expires_at=moment + KEEP_UNLANDED,
        )
        if flight["status"] == lookup.LANDED:
            item.landed(lookup.when(flight.get("arrives")) or moment)
        item.save()
    logger.info("Shared %s (%s)", item.to_string(), item.fr24_id)
    return item, True


def current(item: Share, now: datetime | None = None) -> Shown:
    """Return what link ``item`` shows now, keeping its card up to date."""
    moment = now or timezone.now()
    if not item.is_live(moment):
        return Shown(ENDED, item.snapshot)
    if item.landed_at:
        return Shown(LANDED, item.snapshot)
    try:
        flight = lookup.where(item.flight)
        if flight and flight.get("fr24_id") == item.fr24_id:
            fresh = card(flight)
            landed_at = lookup.when(flight.get("arrives")) if flight["status"] == "landed" else None
        else:
            # Flightradar24 has moved on to a newer leg of the number, or
            # dropped this one: its landing, if any, is in the summaries.
            landed_at = lookup.landing(item.flight, item.fr24_id)
            fresh = touch_down(item.snapshot, landed_at) if landed_at else item.snapshot
    except lookup.NotConnected, lookup.Unavailable:
        # Show the last card rather than nothing; the page says when it was seen.
        return Shown(LIVE, item.snapshot)
    if fresh != item.snapshot or landed_at:
        item.snapshot = fresh
        if landed_at:
            item.landed(landed_at)
        item.save(update_fields=["snapshot", "landed_at", "expires_at", "updated_at"])
    return Shown(LANDED if item.landed_at else LIVE, item.snapshot)


def stop(user: Any, uuid: Any) -> bool:
    """Stop ``user``'s link ``uuid`` at once: it's deleted; return whether there was one."""
    deleted, _ = Share.objects.for_user(user).filter(uuid=uuid).delete()
    if deleted:
        logger.info("Stopped share %s", uuid)
    return bool(deleted)


def clear(now: datetime | None = None) -> int:
    """Delete the links that have ended; return how many (the watch_flights cron runs it)."""
    deleted, _ = Share.objects.finished(now).delete()
    if deleted:
        logger.info("Deleted %s ended share links", deleted)
    return deleted


def url(item: Share) -> str:
    """Return the link's public address."""
    return f"{settings.SITE_URL}{reverse('shares:page', args=[item.token])}"


def card(flight: dict[str, Any]) -> dict[str, Any]:
    """Return a lookup as the card draws it: local clocks added, cities named."""
    origin, destination = flight["origin"], flight["destination"]
    return flight | {
        "origin": origin | {"city": city(origin["code"])},
        "destination": destination | {"city": city(destination["code"])},
        "departed_local": clock(flight.get("departed"), origin["tz"]),
        "arrives_local": clock(flight.get("arrives"), destination["tz"]),
        "seen_utc": clock(flight.get("seen"), "UTC"),
    }


def touch_down(snapshot: dict[str, Any], landed_at: datetime) -> dict[str, Any]:
    """Return a card as it looks once its leg landed at ``landed_at``."""
    arrives = landed_at.isoformat()
    return snapshot | {
        "status": lookup.LANDED,
        "arrives": arrives,
        "arrives_local": clock(arrives, snapshot["destination"]["tz"]),
        "progress": 1.0,
        "position": None,
        "position_kind": None,
        "altitude_ft": None,
        "minutes_to_go": None,
    }


def city(code: str) -> str:
    """Return the city of the airport with ``code``, or "" if it isn't stored."""
    airport = Airport.objects.with_code(code).first()
    return airport.city if airport else ""


def clock(moment: str | None, tz: str) -> str | None:
    """Return the ISO time ``moment`` as HH:MM in the time zone ``tz``, or None."""
    if not moment:
        return None
    return datetime.fromisoformat(moment).astimezone(ZoneInfo(tz)).strftime("%H:%M")
