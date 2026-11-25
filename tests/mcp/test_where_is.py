"""Tests for the where_is spike tool (RAS-125): sample data, a map view."""

from datetime import UTC, datetime
from typing import Any

import pytest
from freezegun import freeze_time

from apps.mcp.tools import (
    SAMPLE_DESTINATION,
    SAMPLE_ORIGIN,
    ToolError,
    _duration,
    great_circle,
    where_is,
)


@pytest.fixture
def rpc(user: Any) -> Any:
    """Call the MCP view as ``user``, bypassing OAuth."""
    from apps.mcp import views

    def call(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        result: dict[str, Any] = views._dispatch(user, method, params or {})
        return result

    return call


@freeze_time(datetime(2026, 11, 25, 16, 0, tzinfo=UTC))
def test_where_is_answers_in_words_and_names_the_map(rpc: Any) -> None:
    """The model reads one sentence; the view gets the flight as data."""
    described = next(t for t in rpc("tools/list")["tools"] if t["name"] == "where_is")
    assert described["_meta"]["ui"]["resourceUri"] == "ui://flight/map"

    result = rpc("tools/call", {"name": "where_is", "arguments": {"flight": " ba 1234 "}})
    (content,) = result["content"]
    assert content["text"].startswith(
        "BA1234 is in the air from Lisbon (LIS) to London Heathrow (LHR), 38% of the way. "
        "It left at 15:00 local time and lands at 17:40 local time, in 1 h 40 m, "
        "12 minutes late. The map shows its route and where it is now."
    )
    assert "sample data" in content["text"]
    assert "made-up flight" in content["text"]
    flight = result["structuredContent"]
    assert flight["flight"] == "BA1234"
    assert flight["sample"] is True
    assert flight["origin"]["code"] == "LIS"
    assert flight["departed_local"] == "15:00"
    assert flight["arrives_local"] == "17:40"
    assert flight["minutes_to_go"] == 100
    assert flight["progress"] == pytest.approx(60 / 160, abs=0.001)


@pytest.mark.parametrize("flight", ["", "BA", "1234", "BA12345", "hello there", None])
def test_where_is_wants_a_flight_number(flight: Any) -> None:
    """Anything that isn't a flight number is a mistake the model can fix."""
    with pytest.raises(ToolError, match="flight number"):
        where_is(None, {"flight": flight})


@pytest.mark.parametrize("flight", ["BA1234", "EZY8812", "U21", "LH400A"])
def test_where_is_takes_airline_and_icao_numbers(flight: str) -> None:
    """IATA two-letter and ICAO three-letter airline codes both work."""
    assert where_is(None, {"flight": flight})["flight"] == flight


def test_great_circle_ends_at_the_airports() -> None:
    """Fraction 0 is the origin, 1 the destination, and the middle lies between."""
    start = great_circle(SAMPLE_ORIGIN, SAMPLE_DESTINATION, 0)
    end = great_circle(SAMPLE_ORIGIN, SAMPLE_DESTINATION, 1)
    middle = great_circle(SAMPLE_ORIGIN, SAMPLE_DESTINATION, 0.5)
    assert start == pytest.approx(
        {"lat": SAMPLE_ORIGIN["lat"], "lon": SAMPLE_ORIGIN["lon"]}, abs=1e-3
    )
    assert end == pytest.approx(
        {"lat": SAMPLE_DESTINATION["lat"], "lon": SAMPLE_DESTINATION["lon"]}, abs=1e-3
    )
    assert SAMPLE_ORIGIN["lat"] < middle["lat"] < SAMPLE_DESTINATION["lat"]


@pytest.mark.parametrize(
    ("minutes", "words"), [(100, "1 h 40 m"), (120, "2 h"), (25, "25 m"), (0, "0 m")]
)
def test_duration(minutes: int, words: str) -> None:
    """Durations read as people say them."""
    assert _duration(minutes) == words
