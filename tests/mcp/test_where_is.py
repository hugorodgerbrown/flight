"""Tests for the where_is tool (RAS-138): live Flightradar24 data, a map view."""

from datetime import UTC, datetime
from typing import Any

import pytest
from freezegun import freeze_time

from apps.mcp.tools import ToolError, _duration, where_is
from tests import fr24_fake
from tests.fr24_fake import LIVE_BA117, SUMMARY_BA117, SUMMARY_EI154, TRACK_BA117

NOW = datetime(2026, 11, 26, 9, 32, tzinfo=UTC)


@pytest.fixture
def fr24(monkeypatch: Any, settings: Any, db: None) -> dict[str, Any]:
    """Flightradar24, answered from memory."""
    return fr24_fake.install(monkeypatch, settings)


@pytest.fixture
def rpc(user: Any) -> Any:
    """Call the MCP view as ``user``, bypassing OAuth."""
    from apps.mcp import views

    def call(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = views._dispatch(user, method, params or {})
        return result

    return call


@freeze_time(NOW)
def test_a_flight_in_the_air_is_said_in_words_and_named_for_the_map(
    rpc: Any, fr24: dict[str, Any]
) -> None:
    """The model reads the whole answer in the text; the view gets it as data."""
    fr24["live"] = [LIVE_BA117]
    fr24["summaries"] = [SUMMARY_BA117]
    described = next(t for t in rpc("tools/list")["tools"] if t["name"] == "where_is")
    assert described["_meta"]["ui"]["resourceUri"] == "ui://flight/map-v8"

    result = rpc("tools/call", {"name": "where_is", "arguments": {"flight": " ba 117 "}})
    (content,) = result["content"]
    text = content["text"]
    assert text.startswith(
        "BA117 is in the air from London Heathrow Airport (LHR) to John F Kennedy "
        "International Airport (JFK), "
    )
    assert "% of the way, at 36,000 ft." in text
    assert "It took off at 08:36 local time and UTC." in text
    assert "It's due at 11:04 local time (16:04 UTC), in 6 h 33 m." in text
    assert "The map shows its route and where it is now." in text
    assert "can't say whether the flight is late" in text
    assert "sample" not in text
    flight = result["structuredContent"]
    assert flight["status"] == "airborne"
    assert flight["origin"]["code"] == "LHR"
    assert flight["destination"]["tz"] == "America/New_York"
    assert flight["position"] == {"lat": 53.90511, "lon": -8.71522}
    assert 0.05 < flight["progress"] < 0.2
    assert flight["departed_local"] == "08:36"
    assert flight["arrives_local"] == "11:04"
    assert flight["minutes_to_go"] == 393
    assert flight["position_kind"] == "tracked"
    assert flight["seen_utc"] == "09:32"
    assert "delay_minutes" not in flight


@freeze_time(NOW)
def test_a_landed_flight_says_where_and_when(fr24: dict[str, Any]) -> None:
    """Not in the air, but landed in the last day: landed, with the whole route flown."""
    fr24["summaries"] = [SUMMARY_EI154]
    fr24["tracks"] = {"4b2c3d4e": [{"timestamp": "t", "lat": 53.4, "lon": -6.2}]}
    flight = where_is(None, {"flight": "EI154"})
    assert flight["markdown"].startswith(
        "EI154 landed at London Heathrow Airport (LHR) at 08:48 local time and UTC, from Dublin "
        "Airport (DUB). It took off at 07:45 local time and UTC. The map shows the route it flew."
    )
    assert flight["status"] == "landed"
    assert flight["progress"] == 1.0
    assert flight["position"] is None
    assert flight["path"] == [[53.4, -6.2]]


@freeze_time(NOW)
def test_an_estimated_position_is_said_to_be_one(rpc: Any, fr24: dict[str, Any]) -> None:
    """Out of receiver range Flightradar24 estimates the position; the answer says so."""
    fr24["live"] = [{**LIVE_BA117, "source": "ESTIMATED"}]
    fr24["summaries"] = [SUMMARY_BA117]
    flight = where_is(None, {"flight": "BA117"})
    assert flight["status"] == "airborne"
    assert flight["position_kind"] == "estimated"
    assert "Flightradar24 estimates it's" in flight["markdown"]
    assert "worked out, not received" in flight["markdown"]


@freeze_time(NOW)
def test_a_flight_missing_from_the_live_feed_shows_its_last_track_point(
    fr24: dict[str, Any],
) -> None:
    """Still flying but not in the live feed (RAS-140): the track's latest point is shown."""
    fr24["summaries"] = [SUMMARY_BA117]
    fr24["tracks"] = {"42bc74bd": TRACK_BA117}
    flight = where_is(None, {"flight": "BA117"})
    assert flight["status"] == "airborne"
    assert flight["position_kind"] == "last_seen"
    assert flight["position"] == {"lat": 54.9, "lon": -21.6}
    assert flight["altitude_ft"] == 37000
    assert flight["seen_utc"] == "09:31"
    assert 0.2 < flight["progress"] < 0.5
    text = flight["markdown"]
    assert "the last position it recorded, at 09:31 UTC" in text
    assert "no arrival estimate for it right now" in text
    assert fr24["params"][-1] == {"flight_id": "42bc74bd"}


@freeze_time(NOW)
@pytest.mark.parametrize("track", [None, "forbidden", []])
def test_no_position_anywhere_is_said_plainly_without_a_reason(
    fr24: dict[str, Any], track: Any
) -> None:
    """No live row and no track (none, not on the plan, or empty): say so, guess nothing."""
    fr24["summaries"] = [SUMMARY_BA117]
    if track is not None:
        fr24["tracks"] = {"42bc74bd": track}
    flight = where_is(None, {"flight": "BA117"})
    assert flight["markdown"].startswith(
        "Flightradar24 isn't giving a position for BA117 right now, and doesn't say why. "
        "Its latest flight took off from London Heathrow Airport (LHR) at 08:36 local time and UTC "
        "for John F Kennedy International Airport (JFK) and hasn't been reported landed. "
        "Flightradar24 last heard from it at 09:31 UTC."
    )
    assert flight["status"] == "lost"
    for guess in ("range", "ocean", "Atlantic", "coverage"):
        assert guess not in flight["markdown"]


@freeze_time(NOW)
def test_a_flight_without_an_eta_or_take_off_says_so(fr24: dict[str, Any]) -> None:
    """Live but with no ETA and no summary yet: no times are made up."""
    fr24["live"] = [{**LIVE_BA117, "eta": None, "alt": 0}]
    text = where_is(None, {"flight": "BA117"})["markdown"]
    assert "% of the way." in text
    assert "took off" not in text
    assert "Flightradar24 has no arrival estimate for it right now." in text


@freeze_time(NOW)
def test_a_flight_found_by_callsign_names_its_flight_number(fr24: dict[str, Any]) -> None:
    """Asked for the callsign, the answer says the number Flightradar24 lists."""
    fr24["live"] = [LIVE_BA117]
    text = where_is(None, {"flight": "BAW17R"})["markdown"]
    assert "Flightradar24 lists it as BA117." in text
    assert fr24["params"][0] == {"callsigns": "BAW17R"}


@freeze_time(NOW)
def test_a_flight_that_ended_without_a_landing_isnt_called_landed(fr24: dict[str, Any]) -> None:
    """flight_ended alone means "no longer tracked", not "landed"."""
    fr24["summaries"] = [{**SUMMARY_BA117, "flight_ended": True}]
    fr24["tracks"] = {"42bc74bd": TRACK_BA117}
    flight = where_is(None, {"flight": "BA117"})
    assert flight["status"] == "lost"
    assert "hasn't been reported landed" in flight["markdown"]
    # An ended flight's old track isn't passed off as where it is now.
    assert flight["position"] is None
    assert flight["path"] == []


def test_an_unknown_flight_explains_codeshares(fr24: dict[str, Any]) -> None:
    """Nothing in the air or in the last day: a plain answer, with the codeshare tip."""
    with pytest.raises(ToolError, match="no flight AA6143 in the air now") as caught:
        where_is(None, {"flight": "AA6143"})
    assert "operating airline's number" in str(caught.value)


def test_an_unknown_flight_is_an_error_the_card_shows(rpc: Any, fr24: dict[str, Any]) -> None:
    """The client gets isError, so the card shows the sentence instead of a map."""
    result = rpc("tools/call", {"name": "where_is", "arguments": {"flight": "AA6143"}})
    assert result["isError"] is True
    assert "codeshare" in result["content"][0]["text"]


def test_no_key_means_not_connected(fr24: dict[str, Any], settings: Any) -> None:
    """Without FR24_API_KEY nothing is asked, and the answer says why."""
    settings.FR24_API_KEY = ""
    with pytest.raises(ToolError, match="isn't connected to live flight data"):
        where_is(None, {"flight": "BA117"})
    assert fr24["calls"] == []


@pytest.mark.parametrize(
    ("status", "words"),
    [(401, "key was refused"), (402, "key was refused"), (500, "couldn't be reached")],
)
def test_a_failed_lookup_is_one_plain_sentence(
    fr24: dict[str, Any], status: int, words: str
) -> None:
    """Flightradar24 failing is a sentence the model can pass on; the key never appears."""
    fr24["status"] = status
    with pytest.raises(ToolError, match=words) as caught:
        where_is(None, {"flight": "BA117"})
    assert "test-key" not in str(caught.value)


@pytest.mark.parametrize("flight", ["", "BA", "1234", "BA12345", "hello there", None])
def test_where_is_wants_a_flight_number(flight: Any) -> None:
    """Anything that isn't a flight number is a mistake the model can fix."""
    with pytest.raises(ToolError, match="flight number"):
        where_is(None, {"flight": flight})


@pytest.mark.parametrize("flight", ["BA1234", "EZY8812", "U21", "LH400A"])
def test_where_is_takes_airline_and_icao_numbers(fr24: dict[str, Any], flight: str) -> None:
    """IATA two-letter and ICAO three-letter airline codes both get as far as asking."""
    with pytest.raises(ToolError, match=f"no flight {flight} in the air"):
        where_is(None, {"flight": flight})


@pytest.mark.parametrize(
    ("minutes", "words"), [(100, "1 h 40 m"), (120, "2 h"), (25, "25 m"), (0, "0 m")]
)
def test_duration(minutes: int, words: str) -> None:
    """Durations read as people say them."""
    assert _duration(minutes) == words
