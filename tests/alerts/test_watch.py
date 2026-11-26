"""Tests for the watcher: take-offs and landings noticed once, and their alerts sent once."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.core import mail
from freezegun import freeze_time

from apps.alerts import follows, watch
from apps.alerts.models import Follow
from apps.flights.fr24 import SUMMARY, Fr24Api
from tests.factories import FollowFactory, PushSubscriptionFactory, UserFactory
from tests.fr24_fake import LIVE_BA117, SUMMARY_BA117, SUMMARY_EI154

FOLLOWED = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)
TOOK_OFF = datetime(2026, 11, 26, 8, 36, 54, tzinfo=UTC)
LANDED_BA117 = SUMMARY_BA117 | {
    "datetime_landed": "2026-11-26T16:01:10Z",
    "dest_iata_actual": "JFK",
    "flight_ended": True,
}


def api() -> Fr24Api:
    """A client with no pacing, as the tests' fake answers at once."""
    return Fr24Api("test-key", verbosity=0, gap=0, retry=0)


@pytest.fixture
def follower(db: None) -> Any:
    """Someone with an address and one browser with notifications on."""
    user = UserFactory.create(email="pat@example.com")
    PushSubscriptionFactory.create(user=user)
    return user


def test_a_take_off_then_a_landing_each_send_one_alert(
    fr24: dict[str, Any], pushes: list[dict[str, Any]], follower: Any
) -> None:
    """Waiting, then in the air (with its ETA), then landed: two alerts, by email and push."""
    item = FollowFactory.create(user=follower, not_before=FOLLOWED)

    with freeze_time("2026-11-26T08:30:00Z"):
        run = watch.watch(api())
    assert run.events == []
    assert run.checked == 1
    assert fr24["calls"] == [SUMMARY]

    fr24["summaries"] = [SUMMARY_BA117]
    fr24["live"] = [LIVE_BA117]
    with freeze_time("2026-11-26T08:40:00Z"):
        run = watch.watch(api())
    assert [event for _, event in run.events] == [watch.TAKE_OFF]
    item.refresh_from_db()
    assert item.state == "airborne"
    assert (item.fr24_id, item.origin, item.destination) == ("42bc74bd", "LHR", "JFK")
    assert item.took_off_at == TOOK_OFF
    assert item.arrives_at == datetime(2026, 11, 26, 16, 4, 39, tzinfo=UTC)
    assert item.took_off_sent_at is not None
    # Far from its ETA, so it's next checked in ten minutes, not every run.
    assert item.next_check_at == datetime(2026, 11, 26, 8, 50, tzinfo=UTC)
    (email,) = mail.outbox
    assert email.to == ["pat@example.com"]
    assert email.subject == "BA117 has taken off from London (LHR)"
    assert "Left London (LHR) at 08:36." in email.body
    assert "Lands in New York (JFK) about 11:04 local." in email.body
    (pushed,) = pushes
    assert json.loads(pushed["data"])["title"] == "BA117 has taken off"

    with freeze_time("2026-11-26T08:42:00Z"):
        run = watch.watch(api())
    assert run.checked == 0
    assert len(mail.outbox) == 1

    fr24["summaries"] = [LANDED_BA117]
    with freeze_time("2026-11-26T16:03:00Z"):
        run = watch.watch(api())
    assert [event for _, event in run.events] == [watch.LANDING]
    item.refresh_from_db()
    assert item.state == "landed"
    assert item.landed_sent_at is not None
    assert mail.outbox[1].subject == "BA117 has landed in New York (JFK)"
    assert "Landed in New York (JFK) at 11:01 local, 7 h 24 m after take-off." in (
        mail.outbox[1].body
    )

    with freeze_time("2026-11-26T16:05:00Z"):
        run = watch.watch(api())
    assert run.checked == 0
    assert len(mail.outbox) == 2
    assert len(pushes) == 2


def test_a_flight_followed_in_the_air_sends_only_its_landing(
    fr24: dict[str, Any], pushes: list[dict[str, Any]], follower: Any
) -> None:
    """Following a flight already in the air binds that leg, with no take-off alert."""
    fr24["summaries"] = [SUMMARY_BA117]
    fr24["live"] = [LIVE_BA117]
    fr24["tracks"] = {}
    with freeze_time("2026-11-26T09:32:00Z"):
        item, created = follows.follow(follower, "ba 117")
        assert created
        assert item.state == "airborne"
        run = watch.watch(api())
    assert run.events == []
    assert mail.outbox == []
    fr24["summaries"] = [LANDED_BA117]
    with freeze_time("2026-11-26T16:03:00Z"):
        run = watch.watch(api())
    assert [event for _, event in run.events] == [watch.LANDING]


def test_a_leg_that_landed_before_the_follow_is_not_the_one_followed(
    fr24: dict[str, Any], follower: Any
) -> None:
    """Yesterday's (or this morning's) landed leg lends nothing to the next one."""
    item = FollowFactory.create(
        user=follower, flight="EI154", not_before=FOLLOWED + timedelta(hours=2)
    )
    fr24["summaries"] = [SUMMARY_EI154]
    with freeze_time("2026-11-26T10:05:00Z"):
        run = watch.watch(api())
    item.refresh_from_db()
    assert run.events == []
    assert item.fr24_id == ""
    assert item.state == "waiting"


def test_a_landing_seen_before_its_take_off_sends_only_the_landing(
    fr24: dict[str, Any], pushes: list[dict[str, Any]], follower: Any
) -> None:
    """If the watcher missed the take-off (it wasn't running), the stale take-off isn't sent."""
    FollowFactory.create(user=follower, not_before=FOLLOWED)
    fr24["summaries"] = [LANDED_BA117]
    with freeze_time("2026-11-26T16:03:00Z"):
        run = watch.watch(api())
    assert [event for _, event in run.events] == [watch.LANDING]
    assert len(mail.outbox) == 1
    assert "landed" in mail.outbox[0].subject


def test_a_flight_that_never_takes_off_is_given_up_after_a_day(
    fr24: dict[str, Any], follower: Any
) -> None:
    """No take-off within 24 hours ends the follow, without calling Flightradar24."""
    item = FollowFactory.create(user=follower, not_before=FOLLOWED)
    with freeze_time("2026-11-27T08:01:00Z"):
        run = watch.watch(api())
    item.refresh_from_db()
    assert item.state == "ended"
    assert run.ended == [item]
    assert fr24["calls"] == []


def test_a_flight_never_reported_landed_is_given_up(fr24: dict[str, Any], follower: Any) -> None:
    """Twenty hours in the air without a landing ends the follow."""
    item = FollowFactory.create(user=follower, not_before=FOLLOWED, took_off_at=TOOK_OFF)
    with freeze_time("2026-11-27T05:00:00Z"):
        watch.watch(api())
    item.refresh_from_db()
    assert item.state == "ended"


def test_follows_are_asked_about_in_batches_of_fifteen(fr24: dict[str, Any], follower: Any) -> None:
    """Sixteen flight numbers take two summary calls; callsigns go in a call of their own."""
    for n in range(16):
        FollowFactory.create(user=follower, flight=f"BA{100 + n}", not_before=FOLLOWED)
    FollowFactory.create(user=follower, flight="BAW17R", not_before=FOLLOWED)
    FollowFactory.create(user=UserFactory.create(), flight="BA100", not_before=FOLLOWED)
    with freeze_time("2026-11-26T08:30:00Z"):
        run = watch.watch(api())
    assert run.checked == 18
    assert fr24["calls"] == [SUMMARY, SUMMARY, SUMMARY]
    asked = [p.get("flights") or p.get("callsigns") for p in fr24["params"]]
    assert [len(a.split(",")) for a in asked] == [15, 1, 1]
    assert "BAW17R" in fr24["params"][2]["callsigns"]
    assert fr24["params"][0]["flight_datetime_from"] == "2026-11-26 06:00:00"


def test_without_commit_nothing_is_saved_or_sent(
    fr24: dict[str, Any], pushes: list[dict[str, Any]], follower: Any
) -> None:
    """A dry run reports what it would send and changes nothing."""
    item = FollowFactory.create(user=follower, not_before=FOLLOWED)
    fr24["summaries"] = [SUMMARY_BA117]
    fr24["live"] = [LIVE_BA117]
    with freeze_time("2026-11-26T08:40:00Z"):
        run = watch.watch(api(), commit=False)
    assert [event for _, event in run.events] == [watch.TAKE_OFF]
    item.refresh_from_db()
    assert item.state == "waiting"
    assert mail.outbox == []
    assert pushes == []


def test_an_alert_with_both_channels_off_is_still_recorded(
    fr24: dict[str, Any], pushes: list[dict[str, Any]], follower: Any
) -> None:
    """Channels off means no email and no push, but the alert counts as done."""
    item = FollowFactory.create(user=follower, not_before=FOLLOWED, push=False, email=False)
    fr24["summaries"] = [SUMMARY_BA117]
    with freeze_time("2026-11-26T08:40:00Z"):
        watch.watch(api())
    item.refresh_from_db()
    assert item.took_off_sent_at is not None
    assert mail.outbox == []
    assert pushes == []


def test_a_follow_with_no_eta_is_checked_every_run(fr24: dict[str, Any], follower: Any) -> None:
    """Without an ETA (the live feed had none), it's checked each run, and near the ETA too."""
    now = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
    item = FollowFactory.create(user=follower, not_before=FOLLOWED, took_off_at=TOOK_OFF)
    assert watch.next_check(item, now) is None
    item.arrives_at = now + timedelta(minutes=35)
    assert watch.next_check(item, now) is None
    item.arrives_at = now + timedelta(hours=3)
    assert watch.next_check(item, now) == now + watch.CRUISE_CHECK


def changed_mid_run(monkeypatch: Any, change: Any) -> None:
    """Make ``change`` happen while the watcher is asking Flightradar24, as a person might."""
    asked = watch.summaries

    def summaries(*args: Any) -> list[dict[str, Any]]:
        rows = asked(*args)
        change()
        return rows

    monkeypatch.setattr(watch, "summaries", summaries)


def test_a_channel_turned_off_mid_run_stays_off_and_isnt_used(
    fr24: dict[str, Any], pushes: list[dict[str, Any]], follower: Any, monkeypatch: Any
) -> None:
    """The watcher writes only its own fields, and reads the channels again before sending."""
    item = FollowFactory.create(user=follower, not_before=FOLLOWED)
    fr24["summaries"] = [SUMMARY_BA117]
    changed_mid_run(
        monkeypatch, lambda: Follow.objects.filter(pk=item.pk).update(push=False, email=False)
    )
    with freeze_time("2026-11-26T08:40:00Z"):
        run = watch.watch(api())
    assert [event for _, event in run.events] == [watch.TAKE_OFF]
    item.refresh_from_db()
    assert (item.push, item.email) == (False, False)
    assert item.took_off_sent_at is not None
    assert mail.outbox == []
    assert pushes == []


def test_a_follow_stopped_mid_run_stays_stopped_and_sends_nothing(
    fr24: dict[str, Any], pushes: list[dict[str, Any]], follower: Any, monkeypatch: Any
) -> None:
    """Stop pressed while the watcher works: the follow isn't saved back, and no alert goes."""
    item = FollowFactory.create(user=follower, not_before=FOLLOWED)
    fr24["summaries"] = [SUMMARY_BA117]
    changed_mid_run(monkeypatch, lambda: Follow.objects.filter(pk=item.pk).delete())
    with freeze_time("2026-11-26T08:40:00Z"):
        watch.watch(api())
    assert not Follow.objects.exists()
    assert mail.outbox == []
    assert pushes == []


def test_a_follow_stopped_just_before_its_alert_sends_nothing(
    fr24: dict[str, Any], pushes: list[dict[str, Any]], follower: Any, monkeypatch: Any
) -> None:
    """Deleted after the watcher saved it but before the alert: still nothing goes."""
    item = FollowFactory.create(user=follower, not_before=FOLLOWED)
    fr24["summaries"] = [SUMMARY_BA117]
    saved = watch.save

    def save(follow: Follow, now: datetime) -> bool:
        kept = saved(follow, now)
        Follow.objects.filter(pk=item.pk).delete()
        return kept

    monkeypatch.setattr(watch, "save", save)
    said: list[str] = []
    with freeze_time("2026-11-26T08:40:00Z"):
        watch.watch(api(), say=said.append)
    assert said[-1] == "BA117 LHR-JFK: stopped while checking, no alert"
    assert mail.outbox == []
    assert pushes == []


def test_unfollowing_deletes_the_follow(follower: Any) -> None:
    """Unfollow takes the flight off the list."""
    FollowFactory.create(user=follower)
    assert follows.unfollow(follower, "BA117") == 1
    assert not Follow.objects.exists()
