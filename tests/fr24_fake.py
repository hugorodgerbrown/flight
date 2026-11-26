"""A Flightradar24 answered from memory, for tests of anything that looks flights up."""

import io
import json
import urllib.error
import urllib.parse
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
# Airports the bundled list doesn't have, answered by Flightradar24's airport endpoint.
AIRPORTS = {
    "QXA": {
        "name": "Quixley Airfield",
        "iata": "QXA",
        "icao": "QXAA",
        "lat": 52.5,
        "lon": -2.5,
        "city": "Quixley",
        "country": {"code": "GB", "name": "United Kingdom"},
        "timezone": {"name": "Europe/London", "offset": 0},
    },
}


def asked_for(row: dict[str, Any], params: dict[str, str]) -> bool:
    """Filter as Flightradar24 does: by flight number, or by callsign."""
    if "callsigns" in params:
        return row.get("callsign") in params["callsigns"].split(",")
    return row.get("flight") in params.get("flights", "").split(",")


class FakeResponse(io.BytesIO):
    """What urlopen returns: a readable body that works as a context manager."""


def install(monkeypatch: Any, settings: Any) -> dict[str, Any]:
    """Answer Flightradar24 from the returned state; record every call's path.

    ``state["live"]`` and ``state["summaries"]`` are the rows those calls
    answer, filtered by the call's flights or callsigns as Flightradar24
    filters; ``state["airports"]`` the airports by code; ``state["status"]``
    an HTTP status every call answers with instead, if set.
    """
    settings.FR24_API_KEY = "test-key"
    cache.clear()
    state: dict[str, Any] = {
        "live": [],
        "summaries": [],
        "airports": dict(AIRPORTS),
        "status": None,
        "calls": [],
        "params": [],
    }

    def opener(request: Any) -> FakeResponse:
        path, _, query = request.full_url.removeprefix(fr24.BASE_URL).partition("?")
        params = dict(urllib.parse.parse_qsl(query))
        state["calls"].append(path)
        state["params"].append(params)
        if state["status"]:
            body = io.BytesIO(json.dumps({"message": "No"}).encode())
            raise urllib.error.HTTPError(request.full_url, state["status"], "error", {}, body)  # type: ignore[arg-type]
        if path in (fr24.LIVE, fr24.SUMMARY):
            rows = state["live"] if path == fr24.LIVE else state["summaries"]
            answer: Any = {"data": [row for row in rows if asked_for(row, params)]}
        else:
            code = path.split("/")[3]
            answer = state["airports"].get(code)
            if answer is None:
                raise urllib.error.HTTPError(request.full_url, 404, "error", {}, io.BytesIO(b"{}"))  # type: ignore[arg-type]
        return FakeResponse(json.dumps(answer).encode())

    monkeypatch.setattr(fr24, "opener", opener)
    monkeypatch.setattr(fr24, "pause", lambda seconds: None)
    return state
