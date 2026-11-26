"""Where a flight is now, from Flightradar24 (RAS-138).

``where(number)`` asks Flightradar24 for the flight's live position and its
flights over the last day, joins them by leg (``fr24_id``), names the
airports from stored ``Airport`` rows (fetching any new one once), and
returns a plain dict: in the air, landed, or seen taking off but not now
tracked. Flightradar24 tracks aircraft, not airline schedules, so there is
an ETA but no delay.

A lookup is cached for a minute, so a client asking twice doesn't spend
Flightradar24 credits twice.
"""

from __future__ import annotations

import logging
import math
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
# Someone is waiting on a lookup, so calls aren't paced and a rate-limited
# call waits only briefly before its one retry.
RETRY_SECONDS = 2

AIRBORNE = "airborne"
LANDED = "landed"
LOST = "lost"


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


def look_up(api: Fr24Api, number: str, now: datetime) -> dict[str, Any] | None:
    """Ask Flightradar24 about ``number`` and return what it said, as ``where`` does."""
    live = next((r for r in api.get(LIVE, {"flights": number}) if matches(number, r)), None)
    since = now.astimezone(UTC).replace(microsecond=0, tzinfo=None)
    summaries = api.get(
        SUMMARY,
        {
            "flights": number,
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
        "operated_as": str(either.get("flight") or either.get("callsign") or number),
        "callsign": str(either.get("callsign") or ""),
        "aircraft": str((live or summary or {}).get("type") or ""),
        "origin": origin.as_place(),
        "destination": destination.as_place(),
        "departed": iso(took_off),
        "position": None,
        "altitude_ft": None,
        "minutes_to_go": None,
    }
    if live is not None:
        eta = when(live.get("eta"))
        position = {"lat": float(live["lat"]), "lon": float(live["lon"])}
        return flight | {
            "status": AIRBORNE,
            "arrives": iso(eta),
            "minutes_to_go": max(0, round((eta - now).total_seconds() / 60)) if eta else None,
            "progress": progress(origin, destination, position),
            "position": position,
            "altitude_ft": int(live.get("alt") or 0),
        }
    landed = when((summary or {}).get("datetime_landed"))
    if landed or (summary or {}).get("flight_ended"):
        return flight | {"status": LANDED, "arrives": iso(landed), "progress": 1.0}
    return flight | {"status": LOST, "arrives": None, "progress": 0.0}


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
