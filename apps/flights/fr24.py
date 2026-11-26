"""The Flightradar24 API client that Flight's lookups and checks share (RAS-138).

One small client over urllib: the few calls Flight makes, each paced,
counted, logged at INFO (WARNING on failure) and, when someone is
watching, narrated through ``say``. The key goes only in the
Authorization header; it is never printed or logged.

Endpoints and headers come from Flightradar24's Python SDK (fr24sdk 0.3.1).
Python's default User-Agent is refused, so every call sends Flight's own
(docs/decisions/flight-data-comes-from-flightradar24.md).
"""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import timedelta
from typing import Any

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
USER_AGENT = "Flight/1.0"
# How far back a flight summary looks for the flight's latest leg.
SUMMARY_WINDOW = timedelta(days=1)
LIVE = "/live/flight-positions/full"
SUMMARY = "/flight-summary/full"
USAGE = "/usage"
AIRPORT = "/static/airports/{code}/full"
# What each endpoint is called in progress lines.
LABELS = {
    LIVE: "live positions",
    SUMMARY: "flight summaries",
    USAGE: "credits used",
}
# Response headers worth showing at -v 2: never anything that echoes the key.
SHOWN_HEADERS = (
    "content-type",
    "retry-after",
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
)


class Fr24Error(Exception):
    """A call to Flightradar24 that didn't give an answer."""

    def __init__(self, message: str, status: int | None = None) -> None:
        """Keep the HTTP status, if there was one, beside the message."""
        super().__init__(message)
        self.status = status


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


class Stop(Fr24Error):
    """A failure no later call can get past (a refused key, no credits): the run stops."""


def quiet(text: str) -> None:
    """Print nothing; the default for an Fr24Api nobody is watching."""


class Fr24Api:
    """The few Flightradar24 calls Flight makes: paced, counted, logged and narrated."""

    def __init__(
        self,
        key: str,
        say: Callable[[str], None] = quiet,
        verbosity: int = 1,
        planned: int = 0,
        gap: float = GAP_SECONDS,
        retry: float = RETRY_SECONDS,
    ) -> None:
        """Keep the key for the Authorization header; it is never printed or logged.

        ``say`` prints a progress line, ``verbosity`` is the command's, and
        ``planned`` is how many calls the run expects, for "Call 2 of 6".
        ``gap`` is the pause between calls and ``retry`` the wait before a
        rate-limited call is tried again: a batch check paces itself, while a
        lookup someone is waiting on doesn't.
        """
        self.key = key
        self.say = say
        self.verbosity = verbosity
        self.planned = planned
        self.gap = gap
        self.retry = retry
        self.calls = 0

    def get(self, path: str, params: dict[str, str]) -> list[dict[str, Any]]:
        """GET ``path`` and return its ``data`` rows, retrying a 429 once."""
        answer = self.answer(path, params)
        rows = answer.get("data") if isinstance(answer, dict) else None
        return rows if isinstance(rows, list) else []

    def airport(self, code: str) -> dict[str, Any] | None:
        """Return Flightradar24's record of the airport with this IATA or ICAO code."""
        if not code.isalnum():
            return None
        try:
            answer = self.answer(AIRPORT.format(code=code.upper()), {})
        except Fr24Error as exc:
            # 404: no such airport. 403: the plan doesn't include airport details
            # (Airports Full is on Essential and above, not Explorer).
            if exc.status in (403, 404):
                return None
            raise
        return answer if isinstance(answer, dict) and answer.get("lat") is not None else None

    def answer(self, path: str, params: dict[str, str]) -> Any:
        """GET ``path`` and return its JSON, retrying a 429 once."""
        try:
            return self.fetch(path, params)
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise self.failed(path, exc) from exc
            logger.warning("Flightradar24 rate-limited %s; retrying in %ss", path, self.retry)
            self.tell(1, f"  Rate-limited; waiting {self.retry:g}s to try once more.")
            pause(self.retry)
            try:
                return self.fetch(path, params)
            except urllib.error.HTTPError as again:
                raise self.failed(path, again) from again

    def failed(self, path: str, exc: urllib.error.HTTPError) -> Fr24Error:
        """Log an HTTP error with Flightradar24's message and return it as an Fr24Error."""
        error = failure(path, exc)
        logger.warning("Flightradar24 call failed: %s", error)
        return error

    def fetch(self, path: str, params: dict[str, str]) -> Any:
        """Make one paced, logged call to ``path``; an HTTP error is left to the caller."""
        if self.calls and self.gap:
            pause(self.gap)
        self.calls += 1
        flights = params.get("flights", "")
        count = f" for {plural(len(flights.split(',')), 'flight')}" if flights else ""
        of = f" of {self.planned}" if self.planned else ""
        self.tell(1, f"Call {self.calls}{of}: {LABELS.get(path, path)}{count}...")
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"{BASE_URL}{path}{query}"
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
            raise Fr24Error(f"Flightradar24 could not be reached: {type(exc).__name__}.") from exc
        try:
            answer = json.loads(body)
        except ValueError as exc:
            logger.warning("Flightradar24 %s answered something that isn't JSON", path)
            raise Fr24Error(
                f"Flightradar24 answered {path} with something that isn't JSON."
            ) from exc
        rows = answer.get("data") if isinstance(answer, dict) else None
        seen = len(rows) if isinstance(rows, list) else int(isinstance(answer, dict))
        self.record(path, flights, status, started, seen, headers)
        return answer

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
        for row in self.get(USAGE, {"period": "24h"}):
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


def failure(path: str, exc: urllib.error.HTTPError) -> Fr24Error:
    """Return the Fr24Error for an HTTP error on ``path``, with the API's message."""
    said = explanation(exc)
    if exc.code == 401:
        return Stop(f"Flightradar24 refused the key (check FR24_API_KEY).{said}", 401)
    if exc.code == 402:
        return Stop(f"Flightradar24 says the plan has no credits left.{said}", 402)
    if exc.code == 403:
        return Fr24Error(f"Flightradar24 answered 403 (forbidden) for {path}.{said}", 403)
    return Fr24Error(f"Flightradar24 answered {exc.code} for {path}.{said}", exc.code)


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
