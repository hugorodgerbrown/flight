"""Look up real flights on the Flightradar24 API to see what it covers and costs (RAS-134).

A dev tool, not part of the app: nothing calls it and it saves nothing. With
no arguments it lists the 20 flights it would look up and spends nothing.
``--commit`` asks Flightradar24 for each flight's live position and its
summary over the last day, 15 flights to a call, then prints what each
answer held and the credits Flightradar24 counted. ``--usage`` prints the
account's credits for the last 24 hours. If the credits can't be read, the
lookups still run and the credits are reported as unknown.

It says what it is doing (RAS-137): a line before and after every call on
the console (``-v 2`` adds the URL and rate-limit headers, ``-v 0`` prints
only the report), and an INFO log line per call, WARNING on failure, which
reach Render's logs. A failed batch is marked in the report rather than
stopping the run; only a refused key or an empty plan stops it. The key is
never printed or logged.

Run it where FR24_API_KEY is set, such as the Render shell::

    python manage.py fr24_check --commit
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

logger = logging.getLogger(__name__)

BASE_URL = "https://fr24api.flightradar24.com/api"
API_VERSION = "v1"
TIMEOUT = 30
# Flightradar24 takes up to 15 flight numbers in one call.
BATCH = 15
# A gap between calls keeps well under any plan's rate limit.
GAP_SECONDS = 6.5
# A rate-limited call (429) waits this long and is tried once more.
RETRY_SECONDS = 30
# Python's default User-Agent (Python-urllib) is refused by bot protection.
USER_AGENT = "Flight/1.0 (fr24_check)"
# How far back a flight summary looks for the flight's latest leg.
SUMMARY_WINDOW = timedelta(days=1)
# What each endpoint is called in progress lines.
LABELS = {
    "/live/flight-positions/full": "live positions",
    "/flight-summary/full": "flight summaries",
    "/usage": "credits used",
}
# Response headers worth showing at -v 2: never anything that echoes the key.
SHOWN_HEADERS = (
    "content-type",
    "retry-after",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
)

# Short-haul, long-haul and codeshare numbers, mostly daily, so most are
# found on any day. The last two are codeshares sold under one airline and
# flown by another: they test whether a marketing number finds the flight.
FLIGHTS = (
    # Short-haul, Europe
    "BA432",  # London Heathrow to Amsterdam
    "TP1350",  # Lisbon to London Heathrow
    "U28812",  # easyJet
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
    # Every URL is BASE_URL plus a fixed path, never one a caller chooses.
    return urllib.request.urlopen(request, timeout=TIMEOUT)  # noqa: S310  # nosemgrep


def pause(seconds: float) -> None:
    """Wait between calls; tests replace this so they don't wait."""
    time.sleep(seconds)


def plural(count: int, word: str) -> str:
    """Return "1 flight" or "2 flights"."""
    return f"{count} {word}{'' if count == 1 else 's'}"


class Stop(CommandError):
    """A failure no later call can get past (a refused key, no credits): the run stops."""


def quiet(text: str) -> None:
    """Print nothing; the default for an Fr24Api nobody is watching."""


class Fr24Api:
    """The few Flightradar24 calls the check makes: paced, counted, logged and narrated."""

    def __init__(
        self,
        key: str,
        say: Callable[[str], None] = quiet,
        verbosity: int = 1,
        planned: int = 0,
    ) -> None:
        """Keep the key for the Authorization header; it is never printed or logged.

        ``say`` prints a progress line, ``verbosity`` is the command's, and
        ``planned`` is how many calls the run expects, for "Call 2 of 6".
        """
        self.key = key
        self.say = say
        self.verbosity = verbosity
        self.planned = planned
        self.calls = 0

    def get(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        """GET ``path`` and return its ``data`` rows, retrying a 429 once."""
        try:
            return self.fetch(path, params)
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise self.failed(path, exc) from exc
            logger.warning("Flightradar24 rate-limited %s; retrying in %ss", path, RETRY_SECONDS)
            self.tell(1, f"  Rate-limited; waiting {RETRY_SECONDS}s to try once more.")
            pause(RETRY_SECONDS)
            try:
                return self.fetch(path, params)
            except urllib.error.HTTPError as again:
                raise self.failed(path, again) from again

    def failed(self, path: str, exc: urllib.error.HTTPError) -> CommandError:
        """Log an HTTP error with Flightradar24's message and return it as a CommandError."""
        error = failure(path, exc)
        logger.warning("Flightradar24 call failed: %s", error)
        return error

    def fetch(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        """Make one paced, logged call to ``path``; an HTTP error is left to the caller."""
        if self.calls:
            pause(GAP_SECONDS)
        self.calls += 1
        flights = params.get("flights", "")
        count = f" for {plural(len(flights.split(',')), 'flight')}" if flights else ""
        of = f" of {self.planned}" if self.planned else ""
        self.tell(1, f"Call {self.calls}{of}: {LABELS.get(path, path)}{count}...")
        url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
        self.tell(2, f"  GET {url}")
        request = urllib.request.Request(  # noqa: S310  # nosemgrep
            url,
            headers={
                "Authorization": f"Bearer {self.key}",
                "Accept": "application/json",
                "Accept-Version": API_VERSION,
                "User-Agent": USER_AGENT,
            },
        )
        started = time.monotonic()
        try:
            with opener(request) as response:
                body = response.read()
                status = getattr(response, "status", 200)
                headers = getattr(response, "headers", None) or {}
        except urllib.error.HTTPError as exc:
            self.record(path, flights, exc.code, started, None, exc.headers or {})
            raise
        except OSError as exc:
            logger.warning("Flightradar24 %s could not be reached: %s", path, type(exc).__name__)
            raise CommandError(
                f"Flightradar24 could not be reached: {type(exc).__name__}."
            ) from exc
        try:
            answer = json.loads(body)
        except ValueError as exc:
            logger.warning("Flightradar24 %s answered something that isn't JSON", path)
            raise CommandError(
                f"Flightradar24 answered {path} with something that isn't JSON."
            ) from exc
        rows = answer.get("data") if isinstance(answer, dict) else None
        rows = rows if isinstance(rows, list) else []
        self.record(path, flights, status, started, len(rows), headers)
        return rows

    def record(
        self,
        path: str,
        flights: str,
        status: int,
        started: float,
        rows: int | None,
        headers: Any,
    ) -> None:
        """Log one call and tell the console how it went."""
        seconds = time.monotonic() - started
        if rows is None:
            logger.warning(
                "Flightradar24 GET %s flights=%s answered %s in %.1fs",
                path,
                flights or "-",
                status,
                seconds,
            )
            self.tell(1, f"  Answered {status} in {seconds:.1f}s.")
        else:
            logger.info(
                "Flightradar24 GET %s flights=%s answered %s in %.1fs with %s rows",
                path,
                flights or "-",
                status,
                seconds,
                rows,
            )
            self.tell(1, f"  Answered {status} in {seconds:.1f}s with {plural(rows, 'row')}.")
        shown = [f"{name}: {headers.get(name)}" for name in SHOWN_HEADERS if headers.get(name)]
        if shown:
            self.tell(2, f"  {'; '.join(shown)}")

    def tell(self, level: int, text: str) -> None:
        """Print ``text`` on the console if the verbosity is at least ``level``."""
        if self.verbosity >= level:
            self.say(text)

    def credits(self) -> dict[str, int]:
        """Return the credits used in the last 24 hours, by endpoint."""
        used: dict[str, int] = {}
        for row in self.get("/usage", {"period": "24h"}):
            endpoint = str(row.get("endpoint") or "other")
            used[endpoint] = used.get(endpoint, 0) + int(row.get("credits") or 0)
        return used


def explanation(exc: urllib.error.HTTPError) -> str:
    """Return Flightradar24's own message and details from an error body, if any."""
    try:
        body = json.loads(exc.read() or b"{}")
    except OSError, ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    said = ". ".join(str(body[k]).rstrip(".") for k in ("message", "details") if body.get(k))
    return f" Flightradar24 said: {said}." if said else ""


def failure(path: str, exc: urllib.error.HTTPError) -> CommandError:
    """Return the CommandError for an HTTP error on ``path``, with the API's message."""
    said = explanation(exc)
    if exc.code == 401:
        return Stop(f"Flightradar24 refused the key (check FR24_API_KEY).{said}")
    if exc.code == 402:
        return Stop(f"Flightradar24 says the plan has no credits left.{said}")
    if exc.code == 403:
        return CommandError(f"Flightradar24 answered 403 (forbidden) for {path}.{said}")
    return CommandError(f"Flightradar24 answered {exc.code} for {path}.{said}")


def matches(asked: str, row: dict[str, Any]) -> bool:
    """True if ``row`` is the flight asked for, by flight number or callsign."""
    return asked.upper() in {str(row.get(k) or "").upper() for k in ("flight", "callsign")}


def latest(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the leg that took off most recently, or None."""
    return max(rows, key=lambda r: str(r.get("datetime_takeoff") or ""), default=None)


def pick_summary(
    live: dict[str, Any] | None, summaries: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the summary of the same leg as ``live``, or the latest leg if none is live.

    A flight number flies a leg most days, so yesterday's landed leg must not
    lend its landing time to today's flight in the air: legs join by fr24_id.
    """
    if live is None:
        return latest(summaries)
    return next((s for s in summaries if s.get("fr24_id") == live.get("fr24_id")), None)


def summarise(
    asked: str,
    live: dict[str, Any] | None,
    summary: dict[str, Any] | None,
    failed: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Return what Flightradar24 told us about one flight, as the report needs it.

    ``failed`` names the calls that failed for this flight ("live", "summary"),
    so a missing answer isn't mistaken for a negative one.
    """
    either = live or summary or {}
    origin = either.get("orig_iata") or either.get("orig_icao") or "?"
    destination = (
        (summary or {}).get("dest_iata_actual")
        or either.get("dest_iata")
        or either.get("dest_icao")
        or "?"
    )
    return {
        "asked": asked,
        "failed": sorted(failed),
        "found": bool(live or summary),
        "flight": either.get("flight") or either.get("callsign") or "",
        "codeshare": bool(either) and not matches(asked, either),
        "route": f"{origin}-{destination}",
        "airborne": live is not None,
        "position": (
            {k: live.get(k) for k in ("lat", "lon", "alt", "gspeed", "timestamp")} if live else None
        ),
        "eta": (live or {}).get("eta") or "",
        "took_off": (summary or {}).get("datetime_takeoff") or "",
        "landed": (summary or {}).get("datetime_landed") or "",
    }


class Command(BaseCommand):
    """Look up real flights on Flightradar24 and report coverage and credits."""

    help = "Look up 20 real flights on Flightradar24 (dry run unless --commit)."

    def add_arguments(self, parser: CommandParser) -> None:
        """Take optional flight numbers and the --commit and --usage flags."""
        parser.add_argument("flights", nargs="*", help="Flight numbers (default: 20 of them).")
        parser.add_argument("--commit", action="store_true", help="Make the lookups (they cost).")
        parser.add_argument(
            "--usage", action="store_true", help="Print the credits used in the last 24 hours."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Plan the run, and with --commit make it and print the results."""
        flights = [f.upper().replace(" ", "") for f in options["flights"]] or list(FLIGHTS)
        verbosity = options["verbosity"]
        if options["usage"]:
            today = Fr24Api(self.key(), self.progress, verbosity).credits()
            self.stdout.write(f"Credits used in the last 24 hours: {sum(today.values())}.")
            return
        batches = [flights[i : i + BATCH] for i in range(0, len(flights), BATCH)]
        if not options["commit"]:
            self.stdout.write(
                f"Would look up {len(flights)} flights: {', '.join(flights)}.\n"
                f"{len(batches) * 2} calls (live positions and summaries, {BATCH} flights a call). "
                "Dry run; pass --commit."
            )
            return
        key = self.key()
        planned = len(batches) * 2 + 2
        api = Fr24Api(key, self.progress, verbosity, planned)
        if verbosity > 0:
            self.progress(
                f"Looking up {plural(len(flights), 'flight')} in {planned} calls "
                "(2 of them credit reads), "
                f"about {round((planned - 1) * GAP_SECONDS)}s with the gaps between calls. "
                f"FR24_API_KEY is set ({len(key)} characters)."
            )
        logger.info("fr24_check: %s flights in %s calls", len(flights), planned)
        before = self.credits(api)
        now = datetime.now(tz=UTC).replace(microsecond=0, tzinfo=None)
        live_rows: list[dict[str, Any]] = []
        summary_rows: list[dict[str, Any]] = []
        failed: dict[str, set[str]] = {}
        for batch in batches:
            numbers = ",".join(batch)
            calls = (
                (live_rows, "/live/flight-positions/full", {"flights": numbers}),
                (
                    summary_rows,
                    "/flight-summary/full",
                    {
                        "flights": numbers,
                        "flight_datetime_from": str(now - SUMMARY_WINDOW),
                        "flight_datetime_to": str(now),
                    },
                ),
            )
            for (into, path, params), kind in zip(calls, ("live", "summary"), strict=True):
                try:
                    into += api.get(path, params)
                except Stop:
                    raise
                except CommandError as exc:
                    self.stderr.write(f"{LABELS[path].capitalize()} for {numbers} failed: {exc}")
                    for asked in batch:
                        failed.setdefault(asked, set()).add(kind)
        rows = []
        for asked in flights:
            live = next((r for r in live_rows if matches(asked, r)), None)
            summary = pick_summary(live, [r for r in summary_rows if matches(asked, r)])
            rows.append(summarise(asked, live, summary, failed=frozenset(failed.get(asked, ()))))
            if verbosity > 0:
                self.stdout.write(line(rows[-1]))
        after = self.credits(api) if before is not None else None
        used = spent(before, after)
        logger.info(
            "fr24_check: found %s of %s; %s calls; credits %s",
            sum(r["found"] for r in rows),
            len(rows),
            api.calls,
            "unknown" if used is None else sum(used.values()),
        )
        self.stdout.write(report(rows, api.calls, used))

    def progress(self, text: str) -> None:
        """Print a progress line now, so a slow run shows it is working."""
        self.stdout.write(text)
        self.stdout.flush()

    def credits(self, api: Fr24Api) -> dict[str, int] | None:
        """Return the credits used so far, or None (with a warning) if they can't be read."""
        try:
            return api.credits()
        except Stop:
            raise
        except CommandError as exc:
            self.stderr.write(f"Couldn't read the credits, so they're reported as unknown: {exc}")
            return None

    def key(self) -> str:
        """Return FR24_API_KEY, or stop before any call if it isn't set."""
        key: str = settings.FR24_API_KEY
        if not key:
            raise CommandError("FR24_API_KEY is not set.")
        return key


def spent(before: dict[str, int] | None, after: dict[str, int] | None) -> dict[str, int] | None:
    """Return the credits each endpoint used between two reads, or None if either failed."""
    if before is None or after is None:
        return None
    return {k: after[k] - before.get(k, 0) for k in after if after[k] - before.get(k, 0)}


def line(row: dict[str, Any]) -> str:
    """Return one lookup as a line of the progress output."""
    gaps = f" ({gap(row)})" if row["failed"] else ""
    if not row["found"]:
        return f"{row['asked']}: {'lookup failed' if row['failed'] else 'not found'}{gaps}"
    if row["position"]:
        p = row["position"]
        where = f"in the air at {p['lat']}, {p['lon']}, {p['alt']} ft, ETA {row['eta'] or '?'}"
    else:
        where = f"on the ground; last took off {row['took_off'] or '?'}"
    return f"{row['asked']}: {row['flight']} {row['route']}, {where}{gaps}"


def gap(row: dict[str, Any]) -> str:
    """Return which of a flight's calls failed, as in "live position failed"."""
    names = {"live": "live position", "summary": "summary"}
    return " and ".join(names[kind] for kind in row["failed"]) + " failed"


def report(rows: list[dict[str, Any]], calls: int, credits: dict[str, int] | None) -> str:
    """Return the totals as Markdown, ready to paste into the issue."""
    lines = [
        "| Asked | Found as | Route | In the air | Position | ETA | Took off | Landed |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        if not r["found"]:
            missing = f"lookup failed ({gap(r)})" if r["failed"] else "not found"
            lines.append(f"| {r['asked']} | {missing} | | | | | | |")
            continue
        found_as = f"{r['flight']}{' (codeshare)' if r['codeshare'] else ''}"
        if r["failed"]:
            found_as += f" ({gap(r)})"
        # Without a live answer, "not in the air" isn't known.
        airborne = "unknown" if "live" in r["failed"] else ("yes" if r["airborne"] else "no")
        lines.append(
            f"| {r['asked']} | {found_as} | {r['route']} | {airborne} "
            f"| {'yes' if r['position'] else ''} | {r['eta']} | {r['took_off']} | {r['landed']} |"
        )
    found = [r for r in rows if r["found"]]
    failed = [r for r in rows if r["failed"]]
    by_endpoint = ", ".join(f"{k} {v}" for k, v in sorted((credits or {}).items()))
    lines += [
        "",
        f"- Found {len(found)} of {len(rows)}; {sum(r['airborne'] for r in found)} in the air "
        "with a live position.",
        f"- Calls: {calls} (including usage reads). "
        + (
            f"Credits used: {sum(credits.values())}"
            + (f" ({by_endpoint})" if by_endpoint else "")
            + ", by Flightradar24's count for the last 24 hours."
            if credits is not None
            else "Credits used: unknown (the usage read failed)."
        ),
    ]
    if failed:
        partial = sum(r["found"] for r in failed)
        lines.append(
            f"- Lookups with a failed call: {len(failed)}, {partial} of them partly answered "
            "(see the errors above)."
        )
    return "\n".join(lines)
