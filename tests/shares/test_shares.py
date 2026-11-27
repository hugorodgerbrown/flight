"""Tests for making share links and what they show (apps/shares/shares.py, RAS-145)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from freezegun import freeze_time

from apps.alerts.follows import NotAFlightNumber
from apps.flights import lookup
from apps.shares import shares
from apps.shares.models import KEEP_AFTER_LANDING, KEEP_UNLANDED, Share
from tests import fr24_fake
from tests.factories import ShareFactory, UserFactory
from tests.fr24_fake import LIVE_BA117, SUMMARY_BA117, SUMMARY_EI154

NOW = datetime(2026, 11, 26, 9, 32, tzinfo=UTC)


@pytest.fixture
def fr24(monkeypatch: Any, settings: Any, db: None) -> dict[str, Any]:
    """Flightradar24, answered from memory."""
    return fr24_fake.install(monkeypatch, settings)


@pytest.fixture
def airborne(fr24: dict[str, Any]) -> dict[str, Any]:
    """BA117 in the air over Ireland."""
    fr24["live"] = [LIVE_BA117]
    fr24["summaries"] = [SUMMARY_BA117]
    return fr24


@freeze_time(NOW)
def test_sharing_a_flight_in_the_air_pins_the_link_to_its_leg(
    user: Any, airborne: dict[str, Any]
) -> None:
    """The link follows Flightradar24's leg, and lasts two days until a landing is seen."""
    item, created = shares.share(user, "ba 117")
    assert created
    assert (item.flight, item.fr24_id) == ("BA117", "42bc74bd")
    assert item.expires_at == NOW + KEEP_UNLANDED
    assert len(item.token) >= 22
    card = item.snapshot
    assert card["status"] == "airborne"
    assert (card["origin"]["city"], card["destination"]["city"]) == ("London", "New York")
    assert (card["departed_local"], card["arrives_local"]) == ("08:36", "11:04")
    assert item.to_string() == "BA117 LHR-JFK"


@freeze_time(NOW)
def test_sharing_the_same_leg_twice_gives_the_same_link(
    user: Any, airborne: dict[str, Any]
) -> None:
    """Asking again (Claude, then the card's button) doesn't make a second link."""
    first, _ = shares.share(user, "BA117")
    again, created = shares.share(user, "BA117")
    assert (again.pk, created) == (first.pk, False)
    other, created = shares.share(UserFactory.create(), "BA117")
    assert created
    assert other.token != first.token


@freeze_time(NOW)
def test_a_landed_flight_can_be_shared_for_a_day_after_landing(
    user: Any, fr24: dict[str, Any]
) -> None:
    """A link to a landed leg is already landed, and ends a day after the landing."""
    fr24["summaries"] = [SUMMARY_EI154]
    item, _ = shares.share(user, "EI154")
    assert item.landed_at == datetime(2026, 11, 26, 8, 48, 11, tzinfo=UTC)
    assert item.expires_at == item.landed_at + KEEP_AFTER_LANDING
    assert shares.current(item).state == shares.LANDED


@pytest.mark.parametrize("text", ["", "hello", "BA 11 7 7 7"])
def test_sharing_needs_a_flight_number(user: Any, text: str) -> None:
    """Text that isn't a flight number is refused before anything is asked."""
    with pytest.raises(NotAFlightNumber):
        shares.share(user, text)


def test_nothing_in_the_air_means_nothing_to_share(user: Any, fr24: dict[str, Any]) -> None:
    """No leg in the air or just landed: there's nothing for a link to follow."""
    with pytest.raises(shares.NothingToShare):
        shares.share(user, "BA117")
    assert not Share.objects.exists()


def test_no_live_data_is_said(user: Any, settings: Any, db: None) -> None:
    """Without the Flightradar24 key, sharing says so rather than guessing."""
    settings.FR24_API_KEY = ""
    with pytest.raises(lookup.NotConnected):
        shares.share(user, "BA117")


@freeze_time(NOW)
def test_every_viewer_shares_one_lookup_a_minute(airborne: dict[str, Any]) -> None:
    """Fifty page loads of two links to one flight cost what one does."""
    links = [ShareFactory.create(), ShareFactory.create()]
    for _ in range(25):
        for item in links:
            assert shares.current(item).state == shares.LIVE
    looked_up = airborne["calls"].count("/live/flight-positions/full")
    assert looked_up == 1


@freeze_time(NOW)
def test_a_live_link_keeps_its_card_up_to_date(airborne: dict[str, Any]) -> None:
    """The latest lookup of the link's leg becomes its card."""
    item = ShareFactory.create()
    shown = shares.current(item)
    item.refresh_from_db()
    assert shown.flight["position"] == {"lat": 53.90511, "lon": -8.71522}
    assert item.snapshot["position"] == shown.flight["position"]


@freeze_time(NOW)
def test_a_landing_seen_live_ends_the_link_a_day_later(fr24: dict[str, Any]) -> None:
    """Once the leg lands, the link is landed, and asks Flightradar24 nothing more."""
    fr24["summaries"] = [
        SUMMARY_BA117 | {"datetime_landed": "2026-11-26T09:20:00Z", "flight_ended": True}
    ]
    item = ShareFactory.create()
    assert shares.current(item).state == shares.LANDED
    item.refresh_from_db()
    assert item.landed_at == datetime(2026, 11, 26, 9, 20, tzinfo=UTC)
    assert item.expires_at == item.landed_at + KEEP_AFTER_LANDING
    calls = len(fr24["calls"])
    assert shares.current(item).state == shares.LANDED
    assert len(fr24["calls"]) == calls


@freeze_time(NOW)
def test_yesterdays_link_never_shows_todays_flight(fr24: dict[str, Any]) -> None:
    """When the number's next leg is flying, the link shows its own leg, landed."""
    fr24["live"] = [LIVE_BA117 | {"fr24_id": "tomorrow1", "lat": 51.0, "lon": -1.0}]
    fr24["summaries"] = [
        SUMMARY_BA117 | {"fr24_id": "tomorrow1"},
        SUMMARY_BA117 | {"datetime_landed": "2026-11-26T07:00:00Z", "flight_ended": True},
    ]
    item = ShareFactory.create()
    shown = shares.current(item)
    assert shown.state == shares.LANDED
    assert shown.flight["position"] is None
    assert shown.flight["status"] == "landed"
    assert shown.flight["arrives_local"] == "02:00"


@freeze_time(NOW)
def test_a_diversion_seen_late_shows_where_it_really_landed(fr24: dict[str, Any]) -> None:
    """A leg that landed somewhere else, seen only after the next leg flies, says so."""
    fr24["live"] = [LIVE_BA117 | {"fr24_id": "tomorrow1"}]
    fr24["summaries"] = [
        SUMMARY_BA117 | {"fr24_id": "tomorrow1"},
        SUMMARY_BA117
        | {
            "datetime_landed": "2026-11-26T07:00:00Z",
            "flight_ended": True,
            "dest_iata_actual": "LHR",
            "dest_icao_actual": "EGLL",
        },
    ]
    shown = shares.current(ShareFactory.create())
    assert shown.state == shares.LANDED
    assert shown.flight["destination"]["code"] == "LHR"
    assert shown.flight["destination"]["city"] == "London"
    assert shown.flight["arrives_local"] == "07:00"


@freeze_time(NOW)
def test_a_leg_flightradar24_has_dropped_keeps_its_last_card(fr24: dict[str, Any]) -> None:
    """No landing reported for a leg no longer tracked: the last card stays, still live."""
    item = ShareFactory.create(fr24_id="gone1234")
    shown = shares.current(item)
    assert shown.state == shares.LIVE
    assert shown.flight == item.snapshot


@freeze_time(NOW)
def test_a_flightradar24_outage_shows_the_last_card(airborne: dict[str, Any]) -> None:
    """Flightradar24 failing doesn't blank the page: it shows what it last knew."""
    airborne["status"] = 500
    item = ShareFactory.create()
    assert shares.current(item) == shares.Shown(shares.LIVE, item.snapshot)


@freeze_time(NOW)
def test_an_expired_link_has_ended_until_it_is_cleared(fr24: dict[str, Any]) -> None:
    """An ended link shows its last card, asks Flightradar24 nothing, and is then deleted."""
    expired = ShareFactory.create(expires_at=NOW - timedelta(seconds=1))
    live = ShareFactory.create()
    assert shares.current(expired).state == shares.ENDED
    assert fr24["calls"] == []
    assert shares.clear() == 1
    assert list(Share.objects.all()) == [live]


@freeze_time(NOW)
def test_only_the_owner_can_stop_a_link(db: None) -> None:
    """Stopping deletes the link at once, and only for the person who made it."""
    item = ShareFactory.create()
    assert not shares.stop(UserFactory.create(), item.uuid)
    assert shares.stop(item.user, item.uuid)
    assert not shares.stop(item.user, item.uuid)
    assert not Share.objects.exists()


def test_the_link_is_on_the_site(db: None, settings: Any) -> None:
    """The address is the site's, with the token in it."""
    settings.SITE_URL = "https://flight.example"
    item = ShareFactory.create()
    assert shares.url(item) == f"https://flight.example/f/{item.token}/"
