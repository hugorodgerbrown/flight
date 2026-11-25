"""Tests for the aeroapi_check command (RAS-124), with AeroAPI answered in memory."""

import io
import json
import urllib.error
from datetime import UTC, datetime
from typing import Any

import pytest
from django.core.management import CommandError, call_command

from apps.core.management.commands import aeroapi_check

NOW = datetime(2026, 11, 25, 19, 0, tzinfo=UTC)

FLYING = {
    "ident": "BAW117",
    "ident_iata": "BA117",
    "fa_flight_id": "BAW117-1764000000-schedule-0001",
    "operator_iata": "BA",
    "origin": {"code": "EGLL", "code_iata": "LHR"},
    "destination": {"code": "KJFK", "code_iata": "JFK"},
    "status": "En Route / On Time",
    "scheduled_out": "2026-11-25T16:00:00Z",
    "scheduled_on": "2026-11-25T23:40:00Z",
    "estimated_on": "2026-11-25T23:52:00Z",
    "actual_off": "2026-11-25T16:20:00Z",
    "actual_on": None,
    "arrival_delay": 720,
    "progress_percent": 38,
}
POSITION = {"latitude": 55.1, "longitude": -30.2, "altitude": 380, "groundspeed": 480}


class FakeResponse(io.BytesIO):
    """What urlopen returns: a readable body that works as a context manager."""


@pytest.fixture
def aeroapi(monkeypatch: Any, settings: Any) -> dict[str, Any]:
    """Answer AeroAPI from ``answers`` (path to JSON or an HTTP status) and record calls."""
    settings.AEROAPI_KEY = "test-key"
    state: dict[str, Any] = {"calls": [], "answers": {}, "usage": [0.10, 0.125], "pauses": 0}

    def opener(request: Any) -> FakeResponse:
        path = request.full_url.removeprefix(aeroapi_check.BASE_URL).split("?")[0]
        state["calls"].append((path, request.get_header("X-apikey")))
        if path == "/account/usage":
            return FakeResponse(json.dumps({"total_cost": state["usage"].pop(0)}).encode())
        answer = state["answers"].get(path, 404)
        if isinstance(answer, int):
            raise urllib.error.HTTPError(request.full_url, answer, "error", {}, None)  # type: ignore[arg-type]
        return FakeResponse(json.dumps(answer).encode())

    def pause(seconds: float) -> None:
        state["pauses"] += 1

    monkeypatch.setattr(aeroapi_check, "opener", opener)
    monkeypatch.setattr(aeroapi_check, "pause", pause)
    return state


def run(*args: str) -> str:
    """Run the command and return what it printed."""
    out = io.StringIO()
    call_command("aeroapi_check", *args, stdout=out)
    return out.getvalue()


def test_a_dry_run_spends_nothing(aeroapi: dict[str, Any]) -> None:
    """With no arguments it lists the 20 flights and the most they could cost."""
    printed = run()
    assert "Would look up 20 flights" in printed
    assert "about $0.20" in printed
    assert aeroapi["calls"] == []


def test_a_lookup_reports_coverage_position_and_cost(aeroapi: dict[str, Any]) -> None:
    """A flight in the air gets its position; the cost is AeroAPI's own count."""
    aeroapi["answers"] = {
        "/flights/BA117": {"flights": [FLYING]},
        f"/flights/{FLYING['fa_flight_id']}/position": {"last_position": POSITION},
        "/flights/XX1": {"flights": []},
    }
    printed = run("BA117", "xx 1", "--commit")
    assert "BA117: BA117 LHR-JFK, En Route / On Time, 12 min late" in printed
    assert "at 55.1, -30.2" in printed
    assert "| XX1 | not found |" in printed
    assert "Found 1 of 2; 1 with scheduled times." in printed
    assert "In the air: 1, of which 1 had a live position." in printed
    assert "Queries: 3, about $0.015 at the list price." in printed
    assert "usage count was $0.100 before the run" in printed
    assert {key for _, key in aeroapi["calls"]} == {"test-key"}
    assert "test-key" not in printed
    # Three paid queries, so two waits between them.
    assert aeroapi["pauses"] == 2


def test_a_marketing_number_is_marked_as_a_codeshare(aeroapi: dict[str, Any]) -> None:
    """Asked for AA6143, found BA117: that is a codeshare."""
    aeroapi["answers"] = {
        "/flights/AA6143": {"flights": [{**FLYING, "last_position": POSITION}]},
    }
    printed = run("AA6143", "--commit")
    assert "| AA6143 | BA117 (codeshare) |" in printed


def test_usage_it_cannot_read_falls_back_to_the_list_price(
    aeroapi: dict[str, Any], monkeypatch: Any
) -> None:
    """If /account/usage fails, the cost is estimated and says so."""
    aeroapi["usage"] = []
    aeroapi["answers"] = {"/flights/BA117": {"flights": []}}

    original = aeroapi_check.opener

    def no_usage(request: Any) -> Any:
        if "/account/usage" in request.full_url:
            raise urllib.error.HTTPError(request.full_url, 500, "error", {}, None)  # type: ignore[arg-type]
        return original(request)

    monkeypatch.setattr(aeroapi_check, "opener", no_usage)
    printed = run("BA117", "--commit")
    assert "about $0.005 at the list price. AeroAPI's usage count could not be read." in printed


def test_it_needs_a_key(aeroapi: dict[str, Any], settings: Any) -> None:
    """Without AEROAPI_KEY it stops before any query."""
    settings.AEROAPI_KEY = ""
    with pytest.raises(CommandError, match="AEROAPI_KEY is not set"):
        run("--commit")
    assert aeroapi["calls"] == []


@pytest.mark.parametrize(("status", "message"), [(401, "refused the key"), (500, "answered 500")])
def test_errors_stop_the_run(aeroapi: dict[str, Any], status: int, message: str) -> None:
    """A refused key or a server error fails the command (non-zero exit)."""
    aeroapi["answers"] = {"/flights/BA117": status}
    with pytest.raises(CommandError, match=message):
        run("BA117", "--commit")


def test_an_unreachable_api_fails_the_command(aeroapi: dict[str, Any], monkeypatch: Any) -> None:
    """A network failure is a CommandError, not a traceback."""

    def down(request: Any) -> Any:
        raise OSError("no route")

    monkeypatch.setattr(aeroapi_check, "opener", down)
    with pytest.raises(CommandError, match="could not be reached: OSError"):
        run("BA117", "--commit")


def test_pick_prefers_the_flight_in_the_air() -> None:
    """In the air beats the next departure, which beats the latest past one."""
    landed = {
        **FLYING,
        "actual_on": "2026-11-24T23:40:00Z",
        "scheduled_out": "2026-11-24T16:00:00Z",
    }
    tomorrow = {
        **FLYING,
        "actual_off": None,
        "scheduled_out": "2026-11-26T16:00:00Z",
    }
    later = {**tomorrow, "scheduled_out": "2026-11-27T16:00:00Z"}
    assert aeroapi_check.pick([landed, tomorrow, FLYING], NOW) is FLYING
    assert aeroapi_check.pick([later, landed, tomorrow], NOW) is tomorrow
    assert aeroapi_check.pick([landed], NOW) is landed
    assert aeroapi_check.pick([], NOW) is None


def test_a_flight_on_the_ground_has_no_position_to_find() -> None:
    """The line for a scheduled flight says it has no position and no delay."""
    row = aeroapi_check.summarise(
        "BA117", {**FLYING, "actual_off": None, "arrival_delay": None}, None
    )
    assert aeroapi_check.line(row).endswith(", no position")
    assert row["delay_minutes"] is None
    assert "on the ground" in aeroapi_check.report([row], 1, None)


def test_an_icao_number_is_not_a_codeshare() -> None:
    """Asking for EZY8812 and getting EZY8812 back (IATA U28812) is the same flight."""
    flight = {**FLYING, "ident": "EZY8812", "ident_icao": "EZY8812", "ident_iata": "U28812"}
    assert not aeroapi_check.codeshare("EZY8812", flight)
    assert not aeroapi_check.codeshare("U28812", flight)
    assert aeroapi_check.codeshare("BA8812", flight)


def test_an_on_time_arrival_is_not_late_however_it_left() -> None:
    """Arrival delay 0 means on time, even after leaving 20 minutes late."""
    row = aeroapi_check.summarise(
        "BA117", {**FLYING, "arrival_delay": 0, "departure_delay": 1200}, None
    )
    assert row["delay_minutes"] == 0
    left_late = aeroapi_check.summarise(
        "BA117", {**FLYING, "arrival_delay": None, "departure_delay": 1200}, None
    )
    assert left_late["delay_minutes"] == 20


def test_usage_reads_the_account_total_for_free(aeroapi: dict[str, Any]) -> None:
    """--usage prints the period's cost so far and makes no paid query."""
    assert run("--usage") == "AeroAPI usage this period: $0.100.\n"
    assert [path for path, _ in aeroapi["calls"]] == ["/account/usage"]


def test_usage_it_cannot_read_fails(aeroapi: dict[str, Any], monkeypatch: Any) -> None:
    """If AeroAPI won't give the total, --usage exits non-zero."""

    def refused(request: Any) -> Any:
        raise urllib.error.HTTPError(request.full_url, 500, "error", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(aeroapi_check, "opener", refused)
    with pytest.raises(CommandError, match="did not say"):
        run("--usage")
