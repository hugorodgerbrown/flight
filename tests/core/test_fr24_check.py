"""Tests for the fr24_check command (RAS-134), with Flightradar24 answered in memory."""

import io
import json
import re
import urllib.error
from typing import Any

import pytest
from django.core.management import CommandError, call_command

from apps.core.management.commands import fr24_check

LIVE = {
    "fr24_id": "3a1b2c3d",
    "flight": "BA117",
    "callsign": "BAW117",
    "lat": 55.1,
    "lon": -30.2,
    "alt": 38000,
    "gspeed": 480,
    "timestamp": "2026-11-25T19:00:00Z",
    "orig_iata": "LHR",
    "dest_iata": "JFK",
    "eta": "2026-11-25T23:52:00Z",
}
SUMMARY = {
    "fr24_id": "3a1b2c3d",
    "flight": "BA117",
    "callsign": "BAW117",
    "orig_iata": "LHR",
    "dest_iata": "JFK",
    "dest_iata_actual": None,
    "datetime_takeoff": "2026-11-25T16:20:00",
    "datetime_landed": None,
    "flight_ended": False,
}
LANDED = {
    "fr24_id": "4b2c3d4e",
    "flight": "EI154",
    "callsign": "EIN154",
    "orig_iata": "DUB",
    "dest_iata": "LHR",
    "dest_iata_actual": "LHR",
    "datetime_takeoff": "2026-11-25T08:00:00",
    "datetime_landed": "2026-11-25T09:10:00",
    "flight_ended": True,
}


class FakeResponse(io.BytesIO):
    """What urlopen returns: a readable body that works as a context manager."""


@pytest.fixture
def fr24(monkeypatch: Any, settings: Any) -> dict[str, Any]:
    """Answer Flightradar24 from ``answers`` (path to rows or an HTTP status); record calls.

    ``errors`` maps a path to statuses answered, one per call (None answers as usual);
    ``body`` is the JSON an error answers with.
    """
    settings.FR24_API_KEY = "test-key"
    state: dict[str, Any] = {
        "calls": [],
        "answers": {},
        "errors": {},
        "body": {},
        "credits": [100, 112],
        "pauses": [],
    }

    def refuse(request: Any, status: int) -> None:
        body = io.BytesIO(json.dumps(state["body"]).encode())
        raise urllib.error.HTTPError(request.full_url, status, "error", {}, body)  # type: ignore[arg-type]

    def opener(request: Any) -> FakeResponse:
        path, _, query = request.full_url.removeprefix(fr24_check.BASE_URL).partition("?")
        state["calls"].append((path, query, dict(request.header_items())))
        if state["errors"].get(path):
            status = state["errors"][path].pop(0)
            if status:
                refuse(request, status)
        if path == "/usage":
            used = state["credits"].pop(0)
            return FakeResponse(json.dumps({"data": [{"credits": used}]}).encode())
        answer = state["answers"].get(path, [])
        if isinstance(answer, int):
            refuse(request, answer)
        return FakeResponse(json.dumps({"data": answer}).encode())

    def pause(seconds: float) -> None:
        state["pauses"].append(seconds)

    monkeypatch.setattr(fr24_check, "opener", opener)
    monkeypatch.setattr(fr24_check, "pause", pause)
    return state


def run(*args: str, err: io.StringIO | None = None) -> str:
    """Run the command and return what it printed."""
    out = io.StringIO()
    call_command("fr24_check", *args, stdout=out, stderr=err or io.StringIO())
    return out.getvalue()


def test_a_dry_run_spends_nothing(fr24: dict[str, Any]) -> None:
    """With no arguments it lists the 20 flights and the calls it would make."""
    printed = run()
    assert "Would look up 20 flights" in printed
    assert "4 calls" in printed
    assert fr24["calls"] == []


def test_a_lookup_reports_coverage_position_and_credits(fr24: dict[str, Any]) -> None:
    """Live and summary answers are joined per flight; credits are Flightradar24's count."""
    fr24["answers"] = {
        "/live/flight-positions/full": [LIVE],
        "/flight-summary/full": [SUMMARY, LANDED],
    }
    printed = run("BA117", "ei 154", "XX1", "--commit")
    assert "BA117: BA117 LHR-JFK, in the air at 55.1, -30.2, 38000 ft" in printed
    assert "EI154: EI154 DUB-LHR, on the ground; last took off 2026-11-25T08:00:00" in printed
    assert "| XX1 | not found |" in printed
    assert "Found 2 of 3; 1 in the air with a live position." in printed
    assert "Calls: 4 (including usage reads). Credits used: 12" in printed
    paths = [path for path, _, _ in fr24["calls"]]
    assert paths == ["/usage", "/live/flight-positions/full", "/flight-summary/full", "/usage"]
    _, query, headers = fr24["calls"][2]
    assert "flights=BA117%2CEI154%2CXX1" in query
    assert "flight_datetime_from=" in query
    assert headers["Authorization"] == "Bearer test-key"
    assert headers["Accept-version"] == "v1"
    assert headers["User-agent"] == fr24_check.USER_AGENT
    assert "test-key" not in printed
    assert fr24["pauses"] == [fr24_check.GAP_SECONDS] * 3


def test_twenty_flights_go_in_two_batches(fr24: dict[str, Any]) -> None:
    """Flightradar24 takes 15 numbers a call, so 20 flights is two of each call."""
    run("--commit")
    paths = [path for path, _, _ in fr24["calls"]]
    assert paths.count("/live/flight-positions/full") == 2
    assert paths.count("/flight-summary/full") == 2


def test_a_marketing_number_is_marked_as_a_codeshare() -> None:
    """Asked for AA6143, Flightradar24's row says BA117: a codeshare."""
    row = fr24_check.summarise("AA6143", LIVE, None)
    assert row["codeshare"]
    assert not fr24_check.summarise("BAW117", LIVE, None)["codeshare"]


def test_the_latest_leg_wins() -> None:
    """Of two legs with one number, the later take-off is the one reported."""
    earlier = {**SUMMARY, "datetime_takeoff": "2026-11-24T16:20:00"}
    assert fr24_check.latest([earlier, SUMMARY]) is SUMMARY
    assert fr24_check.latest([]) is None


def test_usage_reads_the_credits(fr24: dict[str, Any]) -> None:
    """--usage prints the credits used in the last 24 hours."""
    assert run("--usage") == "Credits used in the last 24 hours: 100.\n"


def test_it_needs_a_key(fr24: dict[str, Any], settings: Any) -> None:
    """Without FR24_API_KEY it stops before any call."""
    settings.FR24_API_KEY = ""
    with pytest.raises(CommandError, match="FR24_API_KEY is not set"):
        run("--commit")
    assert fr24["calls"] == []


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "refused the key"),
        (402, "no credits left"),
        (403, "answered 403 \\(forbidden\\) for /live"),
        (500, "answered 500"),
    ],
)
def test_errors_stop_the_run(fr24: dict[str, Any], status: int, message: str) -> None:
    """A refused key, an empty plan or a server error fails the command (non-zero exit)."""
    fr24["answers"] = {"/live/flight-positions/full": status}
    with pytest.raises(CommandError, match=message):
        run("BA117", "--commit")


def test_an_unreachable_api_fails_the_command(fr24: dict[str, Any], monkeypatch: Any) -> None:
    """A network failure is a CommandError, not a traceback."""

    def down(request: Any) -> Any:
        raise OSError("no route")

    monkeypatch.setattr(fr24_check, "opener", down)
    with pytest.raises(CommandError, match="could not be reached: OSError"):
        run("--usage")


def test_an_answer_without_data_is_no_rows(fr24: dict[str, Any], monkeypatch: Any) -> None:
    """A body that isn't {"data": [...]} counts as nothing found."""

    def odd(request: Any) -> FakeResponse:
        return FakeResponse(b'"nothing"')

    monkeypatch.setattr(fr24_check, "opener", odd)
    assert run("--usage") == "Credits used in the last 24 hours: 0.\n"


def test_a_live_leg_takes_only_its_own_summary() -> None:
    """Yesterday's landed leg doesn't make today's flight in the air look landed."""
    yesterday = {
        **SUMMARY,
        "fr24_id": "old",
        "datetime_takeoff": "2026-11-24T16:20:00",
        "datetime_landed": "2026-11-24T23:40:00",
    }
    assert fr24_check.pick_summary(LIVE, [yesterday]) is None
    assert fr24_check.pick_summary(LIVE, [yesterday, SUMMARY]) is SUMMARY
    assert fr24_check.pick_summary(None, [yesterday, SUMMARY]) is SUMMARY


def test_an_error_shows_what_flightradar24_said(fr24: dict[str, Any]) -> None:
    """The API's own message and details go in the error, so a refusal can be told apart."""
    fr24["answers"] = {"/live/flight-positions/full": 403}
    fr24["body"] = {"message": "Forbidden", "details": "Client blocked."}
    with pytest.raises(
        CommandError, match=re.escape("Flightradar24 said: Forbidden. Client blocked.")
    ):
        run("BA117", "--commit")


def test_an_error_body_that_isnt_json_is_left_out() -> None:
    """A body that isn't a JSON object adds nothing to the message."""
    exc = urllib.error.HTTPError("u", 500, "error", {}, io.BytesIO(b"<html>"))  # type: ignore[arg-type]
    assert fr24_check.explanation(exc) == ""
    exc = urllib.error.HTTPError("u", 500, "error", {}, io.BytesIO(b"[1]"))  # type: ignore[arg-type]
    assert fr24_check.explanation(exc) == ""


def test_a_rate_limited_call_is_tried_once_more(fr24: dict[str, Any]) -> None:
    """A 429 waits RETRY_SECONDS and tries again; the run carries on."""
    fr24["errors"] = {"/live/flight-positions/full": [429]}
    fr24["answers"] = {"/live/flight-positions/full": [LIVE]}
    assert "in the air" in run("BA117", "--commit")
    assert fr24_check.RETRY_SECONDS in fr24["pauses"]


def test_a_second_429_stops_the_run(fr24: dict[str, Any]) -> None:
    """Rate-limited twice in a row, the command fails with the API's message."""
    fr24["errors"] = {"/live/flight-positions/full": [429, 429]}
    fr24["body"] = {"message": "Rate limit exceeded"}
    with pytest.raises(CommandError, match=r"answered 429 .*Rate limit exceeded"):
        run("BA117", "--commit")


def test_a_failed_credits_read_doesnt_stop_the_lookups(fr24: dict[str, Any]) -> None:
    """If /usage fails, the lookups still run and the credits are reported as unknown."""
    fr24["errors"] = {"/usage": [403]}
    fr24["answers"] = {"/live/flight-positions/full": [LIVE]}
    err = io.StringIO()
    printed = run("BA117", "--commit", err=err)
    assert "BA117: BA117 LHR-JFK, in the air" in printed
    assert "Credits used: unknown (the usage read failed)." in printed
    assert "Couldn't read the credits" in err.getvalue()
    assert [path for path, _, _ in fr24["calls"]].count("/usage") == 1


def test_a_failed_second_credits_read_is_unknown_too(fr24: dict[str, Any]) -> None:
    """If only the closing /usage read fails, the credits are unknown, not a guess."""
    fr24["errors"] = {"/usage": [None, 500]}
    assert "Credits used: unknown" in run("BA117", "--commit")
