"""Tests for the alerts' words, their email and Web Push."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.core import mail
from pywebpush import WebPushException

from apps.alerts import notify, push
from apps.alerts.models import PushSubscription
from apps.alerts.templatetags.alerts import percent, times
from tests.factories import FollowFactory, PushSubscriptionFactory, UserFactory

TOOK_OFF = datetime(2026, 11, 26, 11, 42, tzinfo=UTC)


@pytest.fixture
def airborne(db: None) -> Any:
    """BA117, in the air from Heathrow to JFK."""
    return FollowFactory.create(
        user=UserFactory.create(email="pat@example.com"),
        origin="LHR",
        destination="JFK",
        took_off_at=TOOK_OFF,
        arrives_at=TOOK_OFF + timedelta(hours=8, minutes=13),
    )


def test_the_take_off_alert_names_both_ends_in_local_time(airborne: Any) -> None:
    """Times are each airport's own; the tag replaces a repeat, the tap opens the app."""
    words = notify.message(airborne, "take_off")
    assert words["title"] == "BA117 has taken off"
    assert words["body"] == (
        "Left London (LHR) at 11:42. Lands in New York (JFK) about 14:55 local."
    )
    assert words["url"] == "/app/"
    assert words["tag"] == f"{airborne.uuid}-take_off"


def test_the_take_off_alert_without_an_eta_or_a_known_airport(db: None) -> None:
    """An airport we don't know is named by its code; no ETA, no time."""
    item = FollowFactory.create(origin="QQQ", destination="", took_off_at=TOOK_OFF)
    assert notify.message(item, "take_off")["body"] == (
        "Left QQQ at 11:42. On its way to its destination."
    )


def test_the_landing_alert_says_how_long_it_took(airborne: Any) -> None:
    """Landed, in the destination's time, and the flight time."""
    airborne.landed_at = TOOK_OFF + timedelta(hours=8, minutes=15)
    words = notify.message(airborne, "landing")
    assert words["subject"] == "BA117 has landed in New York (JFK)"
    assert words["body"] == ("Landed in New York (JFK) at 14:57 local, 8 h 15 m after take-off.")


def test_the_email_has_text_html_and_a_one_click_stop(airborne: Any, settings: Any) -> None:
    """Both parts carry the alert; the stop link is the List-Unsubscribe header too."""
    settings.SITE_URL = "https://flight.example.test"
    notify.send(airborne, "take_off")
    (email,) = mail.outbox
    stop_url = f"https://flight.example.test/alerts/stop/{notify.stop_token(airborne)}/"
    assert email.extra_headers["List-Unsubscribe"] == f"<{stop_url}>"
    assert "List-Unsubscribe-Post" not in email.extra_headers
    assert stop_url in email.body
    assert "https://flight.example.test/app/" in email.body
    assert "We'll email once more when it lands." in email.body
    html, kind = email.alternatives[0]  # type: ignore[attr-defined]
    assert kind == "text/html"
    assert "BA117 is in the air" in html
    assert "about 14:55" in html
    assert stop_url in html
    airborne.refresh_from_db()
    assert airborne.took_off_sent_at is not None


def test_a_failing_email_still_records_the_alert(airborne: Any, monkeypatch: Any) -> None:
    """One channel failing doesn't make the alert repeat on the next run."""

    def broken(*args: Any) -> None:
        raise OSError("SMTP is down")

    monkeypatch.setattr(notify, "send_email", broken)
    notify.send(airborne, "landing")
    airborne.refresh_from_db()
    assert airborne.landed_sent_at is not None


def test_push_goes_to_each_browser_signed_with_the_key(
    airborne: Any, pushes: list[dict[str, Any]]
) -> None:
    """Each subscription gets the encrypted message, with the VAPID claims and a TTL."""
    first = PushSubscriptionFactory.create(user=airborne.user)
    PushSubscriptionFactory.create(user=airborne.user)
    PushSubscriptionFactory.create()
    assert push.send_to_user(airborne.user, notify.message(airborne, "take_off")) == 2
    assert len(pushes) == 2
    sent = pushes[0]
    assert sent["vapid_private_key"] == "private-key-for-tests"
    assert sent["vapid_claims"] == {"sub": "https://flight.example.test"}
    assert sent["ttl"] == push.TTL_SECONDS
    assert set(sent["subscription_info"]) == {"endpoint", "keys"}
    first.refresh_from_db()
    assert first.last_sent_at is not None


def test_push_is_off_without_keys(airborne: Any, settings: Any) -> None:
    """No keys, no pushes, and nothing fails."""
    settings.WEBPUSH_PRIVATE_KEY = ""
    PushSubscriptionFactory.create(user=airborne.user)
    assert push.send_to_user(airborne.user, notify.message(airborne, "take_off")) == 0


class Gone:
    """A push service's answer."""

    def __init__(self, status_code: int) -> None:
        """Keep the status."""
        self.status_code = status_code


@pytest.mark.parametrize(("status", "kept"), [(410, False), (404, False), (500, True)])
def test_a_browser_the_push_service_says_is_gone_is_deleted(
    airborne: Any, pushes: list[Any], monkeypatch: Any, status: int, kept: bool
) -> None:
    """410 and 404 mean the subscription is dead; anything else is tried again next time."""
    PushSubscriptionFactory.create(user=airborne.user)

    def webpush(**kwargs: Any) -> None:
        raise WebPushException("refused", response=Gone(status))

    monkeypatch.setattr(push, "webpush", webpush)
    assert push.send_to_user(airborne.user, notify.message(airborne, "take_off")) == 0
    assert PushSubscription.objects.exists() is kept


def test_a_stored_subscription_off_the_push_services_is_never_called(
    airborne: Any, pushes: list[Any]
) -> None:
    """One saved before endpoints were checked is deleted, not sent to."""
    PushSubscriptionFactory.create(user=airborne.user, endpoint="https://10.0.0.5/hook")
    assert push.send_to_user(airborne.user, notify.message(airborne, "take_off")) == 0
    assert pushes == []
    assert not PushSubscription.objects.exists()


def test_an_unexpected_push_failure_is_logged_not_raised(
    airborne: Any, pushes: list[Any], monkeypatch: Any
) -> None:
    """A network error on one browser doesn't stop the others."""
    PushSubscriptionFactory.create(user=airborne.user)

    def webpush(**kwargs: Any) -> None:
        raise ConnectionError("no route")

    monkeypatch.setattr(push, "webpush", webpush)
    assert push.send_to_user(airborne.user, notify.message(airborne, "take_off")) == 0
    assert PushSubscription.objects.exists()


def test_the_lists_times_for_a_flight_never_reported_landed(db: None) -> None:
    """A follow given up in the air says so."""
    item = FollowFactory.create(took_off_at=TOOK_OFF, ended_at=TOOK_OFF + timedelta(hours=21))
    assert times(item) == "Flightradar24 never reported it landed, so we stopped following it."
    assert percent(0.624) == "62%"


def test_names_and_strings(db: None) -> None:
    """to_string names the flight and route, and the browser."""
    assert FollowFactory.create(origin="LHR", destination="JFK").to_string() == "BA117 LHR-JFK"
    assert FollowFactory.create().to_string() == "BA117"
    assert PushSubscriptionFactory.create(device="").to_string() == "A browser"


def test_durations_leave_out_empty_minutes() -> None:
    """3 h, not 3 h 0 m; 0 m when there's nothing at all."""
    assert notify.duration(TOOK_OFF, TOOK_OFF + timedelta(hours=3)) == "3 h"
    assert notify.duration(TOOK_OFF, TOOK_OFF + timedelta(minutes=95)) == "1 h 35 m"
    assert notify.duration(TOOK_OFF, TOOK_OFF) == "0 m"
