"""Tests for the live flight lookup (RAS-138), with Flightradar24 answered in memory."""

from datetime import UTC, datetime
from typing import Any

import pytest
from freezegun import freeze_time

from apps.flights import fr24, lookup
from apps.flights.models import Airport
from tests import fr24_fake
from tests.fr24_fake import LIVE_BA117, SUMMARY_BA117, SUMMARY_EI154, TRACK_BA117

NOW = datetime(2026, 11, 26, 9, 32, tzinfo=UTC)


@pytest.fixture
def api(monkeypatch: Any, settings: Any, db: None) -> dict[str, Any]:
    """Flightradar24, answered from memory."""
    return fr24_fake.install(monkeypatch, settings)


@freeze_time(NOW)
def test_a_live_flight_joins_its_own_leg(api: dict[str, Any]) -> None:
    """The live row and its summary are one leg; yesterday's landing isn't borrowed."""
    yesterday = {**SUMMARY_EI154, "fr24_id": "old", "flight": "BA117", "callsign": "BAW117"}
    api["live"] = [LIVE_BA117]
    api["summaries"] = [yesterday, SUMMARY_BA117]
    flight = lookup.where("BA117")
    assert flight is not None
    assert flight["status"] == lookup.AIRBORNE
    assert flight["departed"] == "2026-11-26T08:36:54+00:00"
    assert flight["arrives"] == "2026-11-26T16:04:39+00:00"
    assert flight["altitude_ft"] == 36000
    assert flight["aircraft"] == "B772"
    assert api["calls"][:2] == [fr24.LIVE, fr24.SUMMARY]


@freeze_time(NOW)
def test_bundled_airports_cost_no_calls(api: dict[str, Any]) -> None:
    """LHR and JFK are in the bundled list: a lookup is live, summary and track, no more."""
    api["live"] = [LIVE_BA117]
    lookup.where("BA117")
    assert api["calls"] == [fr24.LIVE, fr24.SUMMARY, fr24.TRACKS]


@freeze_time(NOW)
def test_an_airport_the_list_lacks_is_fetched_once_and_kept(api: dict[str, Any]) -> None:
    """A code the bundled list doesn't have is asked for once, then stored."""
    api["live"] = [{**LIVE_BA117, "dest_iata": "QXA"}]
    lookup.where("BA117")
    quixley = Airport.objects.with_code("QXA").get()
    assert (quixley.icao, quixley.country, quixley.tz) == (
        "QXAA",
        "United Kingdom",
        "Europe/London",
    )
    api["calls"].clear()
    lookup.cache.clear()
    lookup.where("BA117")
    assert api["calls"] == [fr24.LIVE, fr24.SUMMARY, fr24.TRACKS]


@pytest.mark.parametrize("status", [403, 404])
def test_an_airport_endpoint_the_plan_lacks_is_no_airport(api: dict[str, Any], status: int) -> None:
    """Explorer has no Airports Full (403); an unknown code is 404: both are just "no airport"."""
    api["status"] = status
    assert fr24.Fr24Api("k", gap=0).airport("QXA") is None


@freeze_time(NOW)
def test_a_lookup_is_cached_for_a_minute(api: dict[str, Any]) -> None:
    """Asking twice within a minute makes the calls once; not found is cached too."""
    api["live"] = [LIVE_BA117]
    first = lookup.where("BA117")
    calls = len(api["calls"])
    assert lookup.where("BA117") == first
    assert len(api["calls"]) == calls
    assert lookup.where("XX1") is None
    assert lookup.where("XX1") is None
    assert len(api["calls"]) == calls + 2


@freeze_time(NOW)
def test_a_diverted_flight_lands_where_it_actually_landed(api: dict[str, Any]) -> None:
    """dest_iata_actual wins over the planned destination."""
    api["summaries"] = [{**SUMMARY_EI154, "dest_iata": "JFK", "dest_iata_actual": "LHR"}]
    flight = lookup.where("EI154")
    assert flight is not None
    assert flight["destination"]["code"] == "LHR"


@freeze_time(NOW)
def test_a_flight_without_a_route_cant_be_mapped(api: dict[str, Any]) -> None:
    """No origin code, or an airport Flightradar24 doesn't know: say so plainly."""
    api["live"] = [{**LIVE_BA117, "orig_iata": None, "orig_icao": None}]
    with pytest.raises(lookup.Unavailable, match="doesn't know its route"):
        lookup.where("BA117")
    lookup.cache.clear()
    api["live"] = [{**LIVE_BA117, "dest_iata": "ZZZ"}]
    with pytest.raises(lookup.Unavailable, match="doesn't know its route"):
        lookup.where("BA117")


@freeze_time(NOW)
def test_an_airport_with_an_unknown_time_zone_is_kept_in_utc(api: dict[str, Any]) -> None:
    """A time zone Python doesn't know is stored as UTC rather than failing the lookup."""
    api["airports"]["QXA"] = {**fr24_fake.AIRPORTS["QXA"], "timezone": {"name": "Mars/Base"}}
    api["live"] = [{**LIVE_BA117, "dest_iata": "QXA"}]
    lookup.where("BA117")
    assert Airport.objects.with_code("QXA").get().tz == "UTC"


def test_an_airport_code_that_isnt_a_code_isnt_asked_for(api: dict[str, Any]) -> None:
    """Only letters and digits go into the airport URL."""
    assert fr24.Fr24Api("k").airport("../usage") is None
    assert api["calls"] == []


def test_another_airport_failure_is_still_a_failure(api: dict[str, Any]) -> None:
    """Only a 404 means "no such airport"; a 500 is Flightradar24 failing."""
    api["status"] = 500
    with pytest.raises(fr24.Fr24Error):
        fr24.Fr24Api("k", gap=0).airport("LHR")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-11-26T08:36:54Z", datetime(2026, 11, 26, 8, 36, 54, tzinfo=UTC)),
        ("2026-11-26T08:36:54", datetime(2026, 11, 26, 8, 36, 54, tzinfo=UTC)),
        ("", None),
        (None, None),
        ("soon", None),
    ],
)
def test_times_are_read_as_utc(value: Any, expected: datetime | None) -> None:
    """Flightradar24's times are UTC; anything unreadable is no time at all."""
    assert lookup.when(value) == expected


def test_progress_is_flown_over_flown_plus_to_go() -> None:
    """At the origin it's 0, at the destination 1, and an airport to itself is 0."""
    heathrow = Airport(lat=51.47, lon=-0.45)
    kennedy = Airport(lat=40.64, lon=-73.78)
    assert lookup.progress(heathrow, kennedy, {"lat": 51.47, "lon": -0.45}) == 0
    assert lookup.progress(heathrow, kennedy, {"lat": 40.64, "lon": -73.78}) == 1
    assert lookup.progress(heathrow, heathrow, {"lat": 51.47, "lon": -0.45}) == 0


@freeze_time(NOW)
def test_the_path_flown_comes_from_the_track(api: dict[str, Any]) -> None:
    """The leg's track is sent as [lat, lon] pairs for the card to draw (RAS-142)."""
    api["live"] = [LIVE_BA117]
    api["tracks"] = {"42bc74bd": list(reversed(TRACK_BA117))}
    flight = lookup.where("BA117")
    assert flight is not None
    assert flight["path"] == [[54.8, -21.1], [54.9, -21.6]]
    assert api["params"][-1] == {"flight_id": "42bc74bd"}


def test_a_long_track_is_thinned_but_keeps_its_last_point() -> None:
    """At most PATH_POINTS are sent, and the newest is always one of them."""
    track = [{"lat": i / 1000, "lon": -i / 1000} for i in range(1001)]
    path = lookup.thin(track)
    assert len(path) <= lookup.PATH_POINTS + 1
    assert path[0] == [0.0, 0.0]
    assert path[-1] == [1.0, -1.0]
    assert lookup.thin([]) == []
