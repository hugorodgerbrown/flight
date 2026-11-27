"""Where a flight is now, from Flightradar24 (RAS-138).

``where(number)`` asks Flightradar24 for the flight's live position and its
flights over the last day, joins them by leg (``fr24_id``), names the
airports from stored ``Airport`` rows (the bundled list, loaded by
migration; Flightradar24's airport endpoint is tried for any other code, and
isn't on every plan), and
returns a plain dict: in the air, landed, or seen taking off but not now
tracked. Flightradar24 tracks aircraft, not airline schedules, so there is
an ETA but no delay.

Where the position came from is part of the answer (RAS-140): received
(``tracked``), worked out by Flightradar24 out of receiver range
(``estimated``), or, when the live feed leaves out a flight still in the
air, the latest point of its track (``last_seen``). Nothing here guesses
why a position is missing.

A lookup is cached for a minute, so a client asking twice doesn't spend
Flightradar24 credits twice.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.flights.fr24 import (
    LIVE,
    SUMMARY,
    SUMMARY_WINDOW,
    Fr24Api,
    Fr24Error,
    Stop,
    matches,
    pick_summary,
)
from apps.flights.models import Airport

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60
# The most points of a track the card is sent: plenty for a smooth line on a
# 640-wide map, and a small answer.
PATH_POINTS = 200
# Someone is waiting on a lookup, so calls aren't paced and a rate-limited
# call waits only briefly before its one retry.
RETRY_SECONDS = 2

# An ICAO airline code (three letters) makes the number a callsign, such as
# BAW117 or EZY8812, which Flightradar24 filters apart from flight numbers.
CALLSIGN = re.compile(r"^[A-Z]{3}\d")

AIRBORNE = "airborne"
LANDED = "landed"
LOST = "lost"

# Where a position came from.
TRACKED = "tracked"
ESTIMATED = "estimated"
LAST_SEEN = "last_seen"


class NotConnected(Exception):
    """FR24_API_KEY isn't set, so there's no live data to ask."""


class Unavailable(Exception):
    """Flightradar24 didn't answer, or answered without enough to say where the flight is."""


def where(number: str) -> dict[str, Any] | None:
    """Return where flight ``number`` is now, or None if Flightradar24 has no such flight."""
    key: str = settings.FR24_API_KEY
    if not key:
        raise NotConnected
    cache_key = f"flights:where:{number}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached or None
    api = Fr24Api(key, verbosity=0, gap=0, retry=RETRY_SECONDS)
    try:
        flight = look_up(api, number, timezone.now())
    except Stop as exc:
        logger.error("where %s: Flightradar24 stopped the lookup: %s", number, exc)
        raise Unavailable(
            f"Flight's connection to Flightradar24 isn't working (the key was refused or the "
            f"plan has run out of credits), so it can't say where {number} is right now."
        ) from exc
    except Fr24Error as exc:
        logger.warning("where %s: Flightradar24 failed: %s", number, exc)
        raise Unavailable(
            f"Flightradar24 couldn't be reached just now, so Flight can't say where {number} "
            "is. Try again in a minute."
        ) from exc
    logger.info(
        "where %s: %s in %s calls", number, flight["status"] if flight else "not found", api.calls
    )
    cache.set(cache_key, flight or {}, CACHE_SECONDS)
    return flight


def landing(number: str, fr24_id: str) -> tuple[datetime | None, dict[str, Any] | None]:
    """Return when leg ``fr24_id`` of ``number`` landed, and where; (None, None) if not reported.

    Where is the airport it actually landed at, as a card's place, which a
    diversion makes different from the one it was flying to; None when
    Flightradar24 doesn't say.

    A share link follows one leg (RAS-145); once a newer leg of the number is
    what ``where`` answers about, the older leg's landing is in the last
    day's summaries. Cached for a minute, like ``where``.
    """
    key: str = settings.FR24_API_KEY
    if not key:
        raise NotConnected
    cache_key = f"flights:landing:{fr24_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return when(cached[0]), cached[1]
    api = Fr24Api(key, verbosity=0, gap=0, retry=RETRY_SECONDS)
    by = "callsigns" if CALLSIGN.match(number) else "flights"
    since = timezone.now().astimezone(UTC).replace(microsecond=0, tzinfo=None)
    try:
        rows = api.get(
            SUMMARY,
            {
                by: number,
                "flight_datetime_from": str(since - SUMMARY_WINDOW),
                "flight_datetime_to": str(since),
            },
        )
        row = next((r for r in rows if str(r.get("fr24_id") or "") == fr24_id), None) or {}
        landed = str(row.get("datetime_landed") or "")
        code = row.get("dest_iata_actual") or row.get("dest_icao_actual") if landed else ""
        airport = place(api, str(code or ""))
    except Fr24Error as exc:
        logger.warning("landing %s %s: Flightradar24 failed: %s", number, fr24_id, exc)
        raise Unavailable(f"Flightradar24 couldn't be reached to check {number}.") from exc
    at = airport.as_place() if airport else None
    logger.info("landing %s %s: %s %s", number, fr24_id, landed or "not reported", code or "")
    cache.set(cache_key, (landed, at), CACHE_SECONDS)
    return when(landed), at


def look_up(api: Fr24Api, number: str, now: datetime) -> dict[str, Any] | None:
    """Ask Flightradar24 about ``number`` and return what it said, as ``where`` does."""
    by = "callsigns" if CALLSIGN.match(number) else "flights"
    live = next((r for r in api.get(LIVE, {by: number}) if matches(number, r)), None)
    since = now.astimezone(UTC).replace(microsecond=0, tzinfo=None)
    summaries = api.get(
        SUMMARY,
        {
            by: number,
            "flight_datetime_from": str(since - SUMMARY_WINDOW),
            "flight_datetime_to": str(since),
        },
    )
    summary = pick_summary(live, [r for r in summaries if matches(number, r)])
    if live is None and summary is None:
        return None
    either: dict[str, Any] = live or summary or {}
    origin = place(api, code_of(either, "orig"))
    landed_at = (summary or {}).get("dest_iata_actual") or (summary or {}).get("dest_icao_actual")
    destination = place(api, landed_at or code_of(either, "dest"))
    if origin is None or destination is None:
        raise Unavailable(
            f"Flightradar24 has {number} but doesn't know its route, so Flight can't map it."
        )
    took_off = when((summary or {}).get("datetime_takeoff"))
    flight: dict[str, Any] = {
        "flight": number,
        # Flightradar24's id for this leg, empty when it gave none.
        "fr24_id": str(either.get("fr24_id") or ""),
        "operated_as": str(either.get("flight") or either.get("callsign") or number),
        "callsign": str(either.get("callsign") or ""),
        "aircraft": str((live or summary or {}).get("type") or ""),
        "origin": origin.as_place(),
        "destination": destination.as_place(),
        "departed": iso(took_off),
        "position": None,
        "position_kind": None,
        # When Flightradar24 last heard from the aircraft.
        "seen": iso(when(live.get("timestamp") if live else (summary or {}).get("last_seen"))),
        "altitude_ft": None,
        "minutes_to_go": None,
    }
    # The path flown, from the leg's track (RAS-142): one call, for a flight
    # in the air or landed.
    fr24_id = flight["fr24_id"]
    track = api.track(fr24_id) if fr24_id else []
    flight["path"] = thin(track)
    if live is not None:
        eta = when(live.get("eta"))
        estimated = str(live.get("source") or "").upper() == "ESTIMATED"
        return (
            flight
            | {
                "status": AIRBORNE,
                "position_kind": ESTIMATED if estimated else TRACKED,
                "arrives": iso(eta),
                "minutes_to_go": max(0, round((eta - now).total_seconds() / 60)) if eta else None,
            }
            | located(origin, destination, live)
        )
    # Only a detected landing is a landing: flight_ended means "no longer
    # tracked", which a flight that vanished from coverage also is.
    summary = summary or {}
    landed = when(summary.get("datetime_landed"))
    if landed:
        return flight | {"status": LANDED, "arrives": iso(landed), "progress": 1.0}
    if not summary.get("flight_ended") and track:
        # Still being followed, but missing from the live feed: its track
        # has the latest point Flightradar24 holds.
        point = track[-1]
        return (
            flight
            | {
                "status": AIRBORNE,
                "position_kind": LAST_SEEN,
                "seen": iso(when(point.get("timestamp"))) or flight["seen"],
                "arrives": None,
            }
            | located(origin, destination, point)
        )
    return flight | {"status": LOST, "arrives": None, "progress": 0.0, "path": []}


def thin(track: list[dict[str, Any]]) -> list[list[float]]:
    """Return the track as [lat, lon] pairs, at most PATH_POINTS, always keeping the last."""
    step = max(1, math.ceil(len(track) / PATH_POINTS))
    kept = track[::step]
    if track and kept[-1] is not track[-1]:
        kept.append(track[-1])
    return [[round(float(p["lat"]), 4), round(float(p["lon"]), 4)] for p in kept]


def located(origin: Airport, destination: Airport, row: dict[str, Any]) -> dict[str, Any]:
    """Return the position, altitude and progress in a live row or track point."""
    position = {"lat": float(row["lat"]), "lon": float(row["lon"])}
    return {
        "position": position,
        "altitude_ft": int(row.get("alt") or 0),
        "progress": progress(origin, destination, position),
    }


def code_of(row: dict[str, Any], end: str) -> str:
    """Return the IATA code for one end of the flight ("orig" or "dest"), else its ICAO code."""
    return str(row.get(f"{end}_iata") or row.get(f"{end}_icao") or "")


def place(api: Fr24Api, code: str) -> Airport | None:
    """Return the stored airport with ``code``, fetching it from Flightradar24 the first time."""
    if not code:
        return None
    airport = Airport.objects.with_code(code).first()
    if airport is not None:
        return airport
    record = api.airport(code)
    if record is None:
        logger.warning("Flightradar24 has no airport %s", code)
        return None
    zone = (record.get("timezone") or {}).get("name") or ""
    try:
        ZoneInfo(zone)
    except ValueError, ZoneInfoNotFoundError:
        zone = "UTC"
    country = record.get("country") or {}
    airport, _ = Airport.objects.update_or_create(
        icao=str(record.get("icao") or code).upper()[:4],
        defaults={
            "iata": str(record.get("iata") or "").upper()[:3],
            "name": str(record.get("name") or code)[:200],
            "city": str(record.get("city") or "")[:200],
            "country": str(country.get("name") or "")[:200],
            "lat": float(record["lat"]),
            "lon": float(record["lon"]),
            "tz": zone,
        },
    )
    logger.info("Stored airport %s", airport.to_string())
    return airport


def when(value: Any) -> datetime | None:
    """Return a Flightradar24 time (ISO 8601, UTC when no zone is given), or None."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def iso(moment: datetime | None) -> str | None:
    """Return ``moment`` as ISO 8601, or None."""
    return moment.isoformat() if moment else None


def distance(start: dict[str, float], end: dict[str, float]) -> float:
    """Return the angle in radians between two points on the globe (great circle)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (start["lat"], start["lon"], end["lat"], end["lon"]))
    return 2 * math.asin(
        math.sqrt(
            math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        )
    )


def progress(origin: Airport, destination: Airport, position: dict[str, float]) -> float:
    """Return how far along its route the aircraft is: flown over flown plus to go."""
    flown = distance({"lat": origin.lat, "lon": origin.lon}, position)
    to_go = distance(position, {"lat": destination.lat, "lon": destination.lon})
    total = flown + to_go
    return round(flown / total, 3) if total else 0.0
