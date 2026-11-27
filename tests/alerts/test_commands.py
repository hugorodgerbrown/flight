"""Tests for watch_flights and make_push_keys."""

from datetime import timedelta
from io import StringIO
from typing import Any

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone
from py_vapid import Vapid

from apps.alerts.models import Follow
from apps.shares.models import Share
from tests.factories import FollowFactory, ShareFactory
from tests.fr24_fake import LIVE_BA117, SUMMARY_BA117


def run(*args: str) -> str:
    """Run watch_flights and return what it printed."""
    out = StringIO()
    call_command("watch_flights", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_without_commit_it_lists_what_is_due_and_calls_nothing(fr24: dict[str, Any]) -> None:
    """The default is read-only: no credits spent."""
    FollowFactory.create()
    out = run()
    assert "1 follow due for a check." in out
    assert "BA117 (waiting)" in out
    assert "Run with --commit" in out
    assert fr24["calls"] == []


@pytest.mark.django_db
def test_with_commit_it_checks_sends_and_clears(fr24: dict[str, Any], pushes: list[Any]) -> None:
    """A take-off is noticed and sent; a follow finished two days ago is deleted."""
    FollowFactory.create(not_before=timezone.now() - timedelta(hours=1))
    FollowFactory.create(flight="LH903", landed_at=timezone.now() - timedelta(days=2))
    fr24["summaries"] = [SUMMARY_BA117 | {"datetime_takeoff": timezone.now().isoformat()}]
    fr24["live"] = [LIVE_BA117]
    out = run("--commit", "-v", "2")
    assert "BA117 LHR-JFK: take off" in out
    assert "Checked 1 follow in 2 calls: 1 alert sent, 0 given up, 1 cleared." in out
    assert list(Follow.objects.values_list("flight", flat=True)) == ["BA117"]


@pytest.mark.django_db
def test_with_commit_it_deletes_ended_share_links(fr24: dict[str, Any]) -> None:
    """Share links are deleted once they end, as the privacy notice says."""
    live = ShareFactory.create()
    ShareFactory.create(expires_at=timezone.now() - timedelta(minutes=1))
    run("--commit")
    assert list(Share.objects.all()) == [live]


@pytest.mark.django_db
def test_with_nothing_due_it_calls_nothing(fr24: dict[str, Any]) -> None:
    """No follows, no calls."""
    assert "Nothing due. Cleared 0 finished follows." in run("--commit")
    assert fr24["calls"] == []


@pytest.mark.django_db
def test_it_fails_without_a_key_or_when_flightradar24_fails(
    fr24: dict[str, Any], settings: Any
) -> None:
    """A run that can't check exits non-zero, saying why."""
    FollowFactory.create()
    fr24["status"] = 500
    with pytest.raises(CommandError, match="Flightradar24 failed"):
        run("--commit")
    settings.FR24_API_KEY = ""
    with pytest.raises(CommandError, match="FR24_API_KEY"):
        run("--commit")


def test_make_push_keys_prints_a_working_pair() -> None:
    """The private key signs with pywebpush's VAPID library; the public key is a P-256 point."""
    out = StringIO()
    call_command("make_push_keys", stdout=out)
    lines = dict(line.split("=", 1) for line in out.getvalue().split())
    assert len(lines["WEBPUSH_PUBLIC_KEY"]) == 87
    signed = Vapid.from_string(lines["WEBPUSH_PRIVATE_KEY"]).sign(
        {"sub": "https://flight.example.test", "aud": "https://push.example.test"}
    )
    assert signed["Authorization"].startswith("vapid t=")
