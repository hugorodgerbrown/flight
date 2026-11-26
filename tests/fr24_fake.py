"""A Flightradar24 answered from memory, for tests of anything that looks flights up."""

import io
import json
import urllib.error
from typing import Any

from django.core.cache import cache

from apps.flights import fr24

LIVE_BA117 = {
    "fr24_id": "42bc74bd",
    "flight": "BA117",
    "callsign": "BAW17R",
    "lat": 53.90511,
    "lon": -8.71522,
    "alt": 36000,
    "gspeed": 401,
    "timestamp": "2026-11-26T09:32:20Z",
    "type": "B772",
    "orig_iata": "LHR",
    "orig_icao": "EGLL",
    "dest_iata": "JFK",
    "dest_icao": "KJFK",
    "eta": "2026-11-26T16:04:39Z",
}
SUMMARY_BA117 = {
    "fr24_id": "42bc74bd",
    "flight": "BA117",
    "callsign": "BAW17R",
    "orig_iata": "LHR",
    "dest_iata": "JFK",
    "dest_iata_actual": None,
    "datetime_takeoff": "2026-11-26T08:36:54Z",
    "datetime_landed": None,
    "flight_ended": False,
}
SUMMARY_EI154 = {
    "fr24_id": "4b2c3d4e",
    "flight": "EI154",
    "callsign": "EIN154",
    "orig_iata": "DUB",
    "dest_iata": "LHR",
    "dest_iata_actual": "LHR",
    "datetime_takeoff": "2026-11-26T07:45:31Z",
    "datetime_landed": "2026-11-26T08:48:11Z",
    "flight_ended": True,
}
AIRPORTS = {
    "LHR": {
        "name": "London Heathrow Airport",
        "iata": "LHR",
        "icao": "EGLL",
        "lat": 51.4706,
        "lon": -0.461941,
        "city": "London",
        "country": {"code": "GB", "name": "United Kingdom"},
        "timezone": {"name": "Europe/London", "offset": 0},
    },
    "JFK": {
        "name": "New York John F. Kennedy International Airport",
        "iata": "JFK",
        "icao": "KJFK",
        "lat": 40.6398,
        "lon": -73.7789,
        "city": "New York",
        "country": {"code": "US", "name": "United States"},
        "timezone": {"name": "America/New_York", "offset": -18000},
    },
    "DUB": {
        "name": "Dublin Airport",
        "iata": "DUB",
        "icao": "EIDW",
        "lat": 53.4213,
        "lon": -6.27007,
        "city": "Dublin",
        "country": {"code": "IE", "name": "Ireland"},
        "timezone": {"name": "Europe/Dublin", "offset": 0},
    },
}


class FakeResponse(io.BytesIO):
    """What urlopen returns: a readable body that works as a context manager."""


def install(monkeypatch: Any, settings: Any) -> dict[str, Any]:
    """Answer Flightradar24 from the returned state; record every call's path.

    ``state["live"]`` and ``state["summaries"]`` are the rows those calls
    answer; ``state["airports"]`` the airports by code; ``state["status"]`` an
    HTTP status every call answers with instead, if set.
    """
    settings.FR24_API_KEY = "test-key"
    cache.clear()
    state: dict[str, Any] = {
        "live": [],
        "summaries": [],
        "airports": dict(AIRPORTS),
        "status": None,
        "calls": [],
    }

    def opener(request: Any) -> FakeResponse:
        path = request.full_url.removeprefix(fr24.BASE_URL).partition("?")[0]
        state["calls"].append(path)
        if state["status"]:
            body = io.BytesIO(json.dumps({"message": "No"}).encode())
            raise urllib.error.HTTPError(request.full_url, state["status"], "error", {}, body)  # type: ignore[arg-type]
        if path == fr24.LIVE:
            answer: Any = {"data": state["live"]}
        elif path == fr24.SUMMARY:
            answer = {"data": state["summaries"]}
        else:
            code = path.split("/")[3]
            answer = state["airports"].get(code)
            if answer is None:
                raise urllib.error.HTTPError(request.full_url, 404, "error", {}, io.BytesIO(b"{}"))  # type: ignore[arg-type]
        return FakeResponse(json.dumps(answer).encode())

    monkeypatch.setattr(fr24, "opener", opener)
    monkeypatch.setattr(fr24, "pause", lambda seconds: None)
    return state
