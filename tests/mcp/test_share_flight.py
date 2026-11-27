"""Tests for the share_flight tool (RAS-145): a live link Claude can hand the user."""

from datetime import UTC, datetime
from typing import Any

import pytest
from freezegun import freeze_time

from apps.mcp.tools import TOOLS, ToolError, share_flight
from apps.shares.models import Share
from tests import fr24_fake
from tests.fr24_fake import LIVE_BA117, SUMMARY_BA117

NOW = datetime(2026, 11, 26, 9, 32, tzinfo=UTC)


@pytest.fixture
def fr24(monkeypatch: Any, settings: Any, db: None) -> dict[str, Any]:
    """Flightradar24, answered from memory."""
    settings.SITE_URL = "https://flight.example"
    return fr24_fake.install(monkeypatch, settings)


@freeze_time(NOW)
def test_share_flight_gives_the_link_and_says_who_can_open_it(
    user: Any, fr24: dict[str, Any]
) -> None:
    """The answer is the link, who can open it, for how long, and how to stop it."""
    fr24["live"] = [LIVE_BA117]
    fr24["summaries"] = [SUMMARY_BA117]
    result = share_flight(user, {"flight": "BA117"})
    item = Share.objects.get(user=user)
    assert result["url"] == f"https://flight.example/f/{item.token}/"
    assert result["created"] is True
    text = result["markdown"]
    assert f"Here's a live link to BA117 LHR-JFK: {result['url']}" in text
    assert "without signing in, until a day after it lands" in text
    assert "https://flight.example/app/account/#sharing" in text
    again = share_flight(user, {"flight": "BA117"})
    assert again["url"] == result["url"]
    assert again["markdown"].startswith("The user already has a link to this flight")


@freeze_time(NOW)
def test_nothing_to_share_is_explained(user: Any, fr24: dict[str, Any]) -> None:
    """A flight not yet flying gets a reason Claude can pass on."""
    with pytest.raises(ToolError, match="isn't in the air or landed in the last day"):
        share_flight(user, {"flight": "BA117"})


def test_share_flight_wants_a_flight_number(user: Any) -> None:
    """Not a number: a mistake the model can fix."""
    with pytest.raises(ToolError, match="flight number"):
        share_flight(user, {"flight": "to mum"})


def test_share_flight_without_live_data(user: Any, settings: Any) -> None:
    """No Flightradar24 key: said plainly."""
    settings.FR24_API_KEY = ""
    with pytest.raises(ToolError, match="isn't connected"):
        share_flight(user, {"flight": "BA117"})


def test_share_flight_when_flightradar24_fails(user: Any, fr24: dict[str, Any]) -> None:
    """Flightradar24 down: its own sentence."""
    fr24["status"] = 500
    with pytest.raises(ToolError, match="couldn't be reached"):
        share_flight(user, {"flight": "BA117"})


def test_share_flight_is_listed_as_a_write_that_reaches_out() -> None:
    """It saves a link, so it isn't read-only, and it asks Flightradar24."""
    hints = TOOLS["share_flight"].describe()["annotations"]
    assert hints["readOnlyHint"] is False
    assert hints["destructiveHint"] is False
    assert hints["openWorldHint"] is True
