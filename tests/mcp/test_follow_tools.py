"""Tests for the follow, unfollow and following MCP tools (RAS-144)."""

from typing import Any

import pytest
from freezegun import freeze_time

from apps.alerts.models import Follow
from tests import fr24_fake
from tests.factories import FollowFactory, PushSubscriptionFactory
from tests.fr24_fake import LIVE_BA117, SUMMARY_BA117


@pytest.fixture
def fr24(monkeypatch: Any, settings: Any, db: None) -> dict[str, Any]:
    """Flightradar24, answered from memory."""
    return fr24_fake.install(monkeypatch, settings)


@pytest.fixture
def call(user: Any) -> Any:
    """Call a tool as ``user`` and return its text, or the error the model sees."""
    from apps.mcp import views

    def tool(name: str, arguments: dict[str, Any] | None = None) -> str:
        result = views._dispatch(user, "tools/call", {"name": name, "arguments": arguments or {}})
        text: str = result["content"][0]["text"]
        return text

    return tool


def test_the_tools_are_listed_and_follow_writes(user: Any) -> None:
    """Follow and unfollow change things; following only reads."""
    from apps.mcp import views

    tools = {t["name"]: t for t in views._dispatch(user, "tools/list", {})["tools"]}
    assert tools["follow"]["annotations"]["readOnlyHint"] is False
    assert tools["unfollow"]["annotations"]["readOnlyHint"] is False
    assert tools["following"]["annotations"]["readOnlyHint"] is True


def test_following_a_flight_says_how_the_user_will_hear(
    call: Any, user: Any, fr24: dict[str, Any]
) -> None:
    """Waiting to take off; push with no device yet says where to turn it on."""
    text = call("follow", {"flight": "ba117"})
    assert text.startswith("Flight will tell the user by push and email when BA117 next takes off")
    assert "No device has push notifications turned on yet" in text
    assert Follow.objects.get().user == user
    assert call("follow", {"flight": "BA117"}).startswith("The user already follows BA117.")
    assert Follow.objects.count() == 1


@freeze_time("2026-11-26T09:32:00Z")
def test_following_a_flight_in_the_air(call: Any, user: Any, fr24: dict[str, Any]) -> None:
    """Only the landing is left to tell."""
    fr24["live"] = [LIVE_BA117]
    fr24["summaries"] = [SUMMARY_BA117]
    PushSubscriptionFactory.create(user=user)
    user.email = ""
    user.save()
    text = call("follow", {"flight": "BA117"})
    assert text.startswith(
        "BA117 is already in the air, so Flight will tell the user by push when it lands."
    )
    assert "Email alerts need the user to sign out and in again once." in text


def test_a_bad_number_is_refused(call: Any, db: None) -> None:
    """The model is told what a flight number looks like."""
    assert "flight number such as BA1234" in call("follow", {"flight": "to Paris"})
    assert "flight number such as BA1234" in call("unfollow", {"flight": "?"})


def test_following_lists_and_unfollow_stops(call: Any, user: Any) -> None:
    """The list says each flight's state; unfollowing takes it off."""
    assert call("following").startswith("The user isn't following any flights.")
    FollowFactory.create(user=user, push=False)
    text = call("following")
    assert (
        "- BA117: waiting to take off. We'll tell you when it takes off. Alerts by email." in text
    )
    assert (
        call("unfollow", {"flight": "BA117"}) == "Stopped following BA117: no more alerts for it."
    )
    assert call("unfollow", {"flight": "BA117"}) == "The user wasn't following BA117."
