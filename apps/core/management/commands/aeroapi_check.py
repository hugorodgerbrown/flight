"""Look up real flights on FlightAware AeroAPI to see what it covers and costs (RAS-124).

A dev tool, not part of the app: nothing calls it and it saves nothing. With
no arguments it lists the 20 flights it would look up and what that may
cost, and spends nothing. ``--commit`` makes the lookups, one query per
flight plus one for the position of each flight in the air, paced for the
Personal tier's 10 queries a minute, then prints what each answer held and
what the run cost (from AeroAPI's own usage count, which is free to read).

Run it where AEROAPI_KEY is set, such as the Render shell::

    uv run python manage.py aeroapi_check --commit
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

logger = logging.getLogger(__name__)

BASE_URL = "https://aeroapi.flightaware.com/aeroapi"
TIMEOUT = 15
# Personal allows 10 result sets a minute; one every 6.5 s stays under it.
GAP_SECONDS = 6.5
# The published price of one GET /flights/{ident} result set (15 flights).
PRICE_PER_QUERY = 0.005

# Short-haul, long-haul and codeshare numbers, mostly daily, so most are
# found on any day. The last two are codeshares sold under one airline and
# flown by another: they test whether AeroAPI finds a marketing number.
FLIGHTS = (
    # Short-haul, Europe
    "BA432",  # London Heathrow to Amsterdam
    "TP1350",  # Lisbon to London Heathrow
    "EZY8812",  # easyJet
    "FR1",  # Ryanair
    "LX318",  # London Heathrow to Zurich
    "EI154",  # Dublin to London Heathrow
    "AF1680",  # Paris to London Heathrow
    "LH900",  # Frankfurt to London Heathrow
    # Long-haul
    "BA117",  # London Heathrow to New York JFK
    "BA15",  # London Heathrow to Singapore
    "VS3",  # London Heathrow to New York JFK
    "AA100",  # New York JFK to London Heathrow
    "DL1",  # New York JFK to London Heathrow
    "UA901",  # San Francisco to London Heathrow
    "EK1",  # Dubai to London Heathrow
    "QF1",  # Sydney to London via Singapore
    "SQ322",  # Singapore to London Heathrow
    "LH400",  # Frankfurt to New York JFK
    # Codeshares
    "AA6143",  # American's number on a British Airways flight
    "IB4218",  # Iberia's number on a British Airways flight
)


def opener(request: urllib.request.Request) -> Any:
    """Open ``request``; tests replace this to answer without the network."""
    # Every URL is BASE_URL plus a quoted path, never one a caller chooses.
    return urllib.request.urlopen(request, timeout=TIMEOUT)  # noqa: S310  # nosemgrep


def pause(seconds: float) -> None:
    """Wait between queries; tests replace this so they don't wait."""
    time.sleep(seconds)


class AeroApi:
    """The few AeroAPI calls the check makes, paced and counted."""

    def __init__(self, key: str) -> None:
        """Keep the key for the x-apikey header; it is never printed or logged."""
        self.key = key
        self.queries = 0

    def get(self, path: str, params: dict[str, str] | None = None, paid: bool = True) -> Any:
        """GET ``path`` and return its JSON, or None when AeroAPI has no such flight."""
        if paid:
            if self.queries:
                pause(GAP_SECONDS)
            self.queries += 1
        url = f"{BASE_URL}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(  # noqa: S310  # nosemgrep
            url, headers={"x-apikey": self.key, "Accept": "application/json"}
        )
        try:
            with opener(request) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (401, 403):
                raise CommandError("AeroAPI refused the key (check AEROAPI_KEY).") from exc
            raise CommandError(f"AeroAPI answered {exc.code} for {path}.") from exc
        except (OSError, ValueError) as exc:
            raise CommandError(f"AeroAPI could not be reached: {type(exc).__name__}.") from exc

    def usage(self) -> float | None:
        """Return the account's cost so far this period, or None if AeroAPI won't say."""
        try:
            answer = self.get("/account/usage", paid=False)
        except CommandError:
            return None
        cost = (answer or {}).get("total_cost")
        return float(cost) if isinstance(cost, int | float) else None


def _when(value: Any) -> datetime | None:
    """Parse an AeroAPI timestamp ("2026-11-25T18:05:00Z"), or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def airborne(flight: dict[str, Any]) -> bool:
    """True if the flight has taken off and not yet landed."""
    return bool(flight.get("actual_off")) and not flight.get("actual_on")


def pick(flights: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    """Return the flight a person asking "where is it?" means.

    AeroAPI lists every flight with the number from two days back to two
    days ahead. The one in the air wins; then the next to leave; then the
    one that most recently left.
    """
    if not flights:
        return None
    flying = [f for f in flights if airborne(f) and not f.get("cancelled")]
    if flying:
        return flying[0]

    def departs(flight: dict[str, Any]) -> datetime:
        return (
            _when(flight.get("estimated_out"))
            or _when(flight.get("scheduled_out"))
            or datetime.min.replace(tzinfo=UTC)
        )

    ahead = [f for f in flights if departs(f) >= now and not f.get("actual_off")]
    if ahead:
        return min(ahead, key=departs)
    return max(flights, key=departs)


def summarise(asked: str, flight: dict[str, Any] | None, position: Any) -> dict[str, Any]:
    """Return what one lookup told us, as the table and the totals need it."""
    if flight is None:
        return {"asked": asked, "found": False}
    origin = flight.get("origin") or {}
    destination = flight.get("destination") or {}
    delay = flight.get("arrival_delay") or flight.get("departure_delay")
    lands = flight.get("estimated_on") or flight.get("actual_on") or flight.get("scheduled_on")
    return {
        "asked": asked,
        "found": True,
        "ident": flight.get("ident_iata") or flight.get("ident"),
        "operator": flight.get("operator_iata") or flight.get("operator"),
        "route": f"{origin.get('code_iata') or origin.get('code') or '?'}"
        f"-{destination.get('code_iata') or destination.get('code') or '?'}",
        "status": flight.get("status") or "",
        "has_times": bool(flight.get("scheduled_out") and flight.get("scheduled_on")),
        "lands": lands or "",
        "delay_minutes": round(delay / 60) if isinstance(delay, int | float) else None,
        "progress": flight.get("progress_percent"),
        "airborne": airborne(flight),
        "position": position,
        "codeshare": bool(
            (flight.get("ident_iata") or flight.get("ident") or asked).upper() != asked.upper()
        ),
    }


class Command(BaseCommand):
    """Look up real flights on AeroAPI and report coverage and cost."""

    help = "Look up 20 real flights on AeroAPI (dry run unless --commit)."

    def add_arguments(self, parser: CommandParser) -> None:
        """Take optional flight numbers and the --commit flag."""
        parser.add_argument("flights", nargs="*", help="Flight numbers (default: 20 of them).")
        parser.add_argument("--commit", action="store_true", help="Make the lookups (they cost).")

    def handle(self, *args: Any, **options: Any) -> None:
        """Plan the run, and with --commit make it and print the results."""
        flights = [f.upper().replace(" ", "") for f in options["flights"]] or list(FLIGHTS)
        loud = options["verbosity"] > 0
        if not options["commit"]:
            most = len(flights) * 2 * PRICE_PER_QUERY
            self.stdout.write(
                f"Would look up {len(flights)} flights: {', '.join(flights)}.\n"
                f"At most {len(flights) * 2} queries, about ${most:.2f}. "
                "Dry run; pass --commit."
            )
            return
        key = settings.AEROAPI_KEY
        if not key:
            raise CommandError("AEROAPI_KEY is not set.")
        api = AeroApi(key)
        before = api.usage()
        now = datetime.now(tz=UTC)
        rows = []
        for asked in flights:
            answer = api.get(f"/flights/{urllib.parse.quote(asked)}", {"ident_type": "designator"})
            flight = pick((answer or {}).get("flights") or [], now)
            position = None
            if flight and airborne(flight):
                position = flight.get("last_position")
                if position is None and flight.get("fa_flight_id"):
                    path = f"/flights/{urllib.parse.quote(flight['fa_flight_id'])}/position"
                    position = (api.get(path) or {}).get("last_position")
            rows.append(summarise(asked, flight, position))
            if loud:
                self.stdout.write(line(rows[-1]))
        after = api.usage()
        self.stdout.write(report(rows, api.queries, before, after))


def line(row: dict[str, Any]) -> str:
    """Return one lookup as a line of the progress output."""
    if not row["found"]:
        return f"{row['asked']}: not found"
    where = "no position"
    if row["position"]:
        p = row["position"]
        where = f"at {p.get('latitude')}, {p.get('longitude')}, {p.get('altitude')}00 ft"
    late = "" if row["delay_minutes"] is None else f", {row['delay_minutes']} min late"
    return (
        f"{row['asked']}: {row['ident']} {row['route']}, {row['status']}{late}, "
        f"lands {row['lands'] or '?'}, {where}"
    )


def report(
    rows: list[dict[str, Any]], queries: int, before: float | None, after: float | None
) -> str:
    """Return the totals as Markdown, ready to paste into the issue."""
    found = [r for r in rows if r["found"]]
    flying = [r for r in found if r["airborne"]]
    lines = [
        "| Asked | Found as | Route | Status | Delay | Times | Position |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        if not r["found"]:
            lines.append(f"| {r['asked']} | not found | | | | | |")
            continue
        delay = "" if r["delay_minutes"] is None else f"{r['delay_minutes']} min"
        where = "yes" if r["position"] else ("missing" if r["airborne"] else "on the ground")
        lines.append(
            f"| {r['asked']} | {r['ident']}{' (codeshare)' if r['codeshare'] else ''} | "
            f"{r['route']} | {r['status']} | {delay} | {'yes' if r['has_times'] else 'no'} "
            f"| {where} |"
        )
    cost = (
        f"${after - before:.3f} by AeroAPI's usage count"
        if before is not None and after is not None
        else f"about ${queries * PRICE_PER_QUERY:.3f} at the list price (usage not readable)"
    )
    lines += [
        "",
        f"- Found {len(found)} of {len(rows)}; "
        f"{sum(r['has_times'] for r in found)} with scheduled times.",
        f"- In the air: {len(flying)}, of which {sum(bool(r['position']) for r in flying)} "
        "had a live position.",
        f"- Queries: {queries}. Cost: {cost}.",
    ]
    return "\n".join(lines)
