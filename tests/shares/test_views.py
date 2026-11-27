"""Tests for the share link's page, feed and picture, and making and stopping links (RAS-145)."""

import html
import io
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from freezegun import freeze_time
from PIL import Image

from apps.shares import preview, shares
from apps.shares.models import Share
from tests import fr24_fake
from tests.factories import SHARE_CARD, FollowFactory, ShareFactory, UserFactory
from tests.fr24_fake import LIVE_BA117, SUMMARY_BA117

NOW = datetime(2026, 11, 26, 9, 32, tzinfo=UTC)


@pytest.fixture
def fr24(monkeypatch: Any, settings: Any, db: None) -> dict[str, Any]:
    """Flightradar24 with BA117 in the air."""
    state = fr24_fake.install(monkeypatch, settings)
    state["live"] = [LIVE_BA117]
    state["summaries"] = [SUMMARY_BA117]
    return state


def page_of(item: Share) -> str:
    """Return the link's page address."""
    return reverse("shares:page", args=[item.token])


@freeze_time(NOW)
def test_anyone_with_the_link_sees_the_flight(client: Client, fr24: dict[str, Any]) -> None:
    """Signed out, the page shows the flight in words and the card for the map to fill."""
    item = ShareFactory.create()
    response = client.get(page_of(item))
    assert response.status_code == 200
    content = response.content.decode()
    assert "BA117, London to New York" in content
    assert "BA117 is in the air to John F Kennedy International Airport, due at 11:04" in content
    assert "LHR → JFK" in content
    assert 'class="flight-map" data-map' in content
    assert "share-live--on" in content
    assert response["X-Robots-Tag"] == "noindex, nofollow"
    assert item.user.masked_email not in content


@freeze_time(NOW)
def test_the_page_carries_the_flight_for_the_card_and_polls_the_feed(
    client: Client, fr24: dict[str, Any]
) -> None:
    """share.js reads the flight from the card and asks the feed every 30 seconds."""
    item = ShareFactory.create()
    content = client.get(page_of(item)).content.decode()
    assert f'data-feed-url="{reverse("shares:feed", args=[item.token])}"' in content
    assert 'data-poll-seconds="30"' in content
    for script in ("js/share.js", "vendor/d3_geo.js", "js/flight_land.js", "js/flight_map.js"):
        assert script in content
    assert content.index("js/share.js") < content.index("js/flight_map.js")


@freeze_time(NOW)
def test_the_link_unfurls_with_its_own_picture(client: Client, fr24: dict[str, Any]) -> None:
    """A pasted link shows the flight, its state and a picture drawn for it."""
    item = ShareFactory.create()
    content = client.get(page_of(item)).content.decode()
    assert '<meta property="og:title" content="BA117, London to New York">' in content
    assert reverse("shares:preview", args=[item.token]) in content
    assert "img/share-card.png" not in content


def test_an_unknown_link_is_not_found(client: Client, db: None) -> None:
    """A token that isn't a link is a 404, for the page, the feed and the picture."""
    for name in ("shares:page", "shares:feed", "shares:preview"):
        assert client.get(reverse(name, args=["nope"])).status_code == 404


def test_an_old_link_says_it_has_ended(client: Client, db: None) -> None:
    """Ended links are deleted, so an old one gets a page that says why, not a bare 404."""
    response = client.get(reverse("shares:page", args=["deleted-link"]))
    assert response.status_code == 404
    assert "<h1>This link has ended</h1>" in response.content.decode()


@freeze_time(NOW)
def test_an_ended_link_says_so(client: Client, fr24: dict[str, Any]) -> None:
    """An expired link, until it's cleared, keeps the route but says it has ended."""
    item = ShareFactory.create(expires_at=NOW - timedelta(minutes=1))
    content = client.get(page_of(item)).content.decode()
    assert "This link has ended" in content
    assert "This link to BA117 has ended." in content
    assert "share-live--on" not in content
    assert "status--ended" in content
    assert fr24["calls"] == []


@freeze_time(NOW)
def test_a_landed_link_says_when(client: Client, db: None) -> None:
    """A landed link names the landing time and asks nothing."""
    card = SHARE_CARD | {"status": "landed", "arrives_local": "11:02", "progress": 1.0}
    item = ShareFactory.create(snapshot=card, landed_at=NOW)
    content = client.get(page_of(item)).content.decode()
    assert "BA117 landed at John F Kennedy International Airport at 11:02 local time." in content
    assert "Landed 11:02" in content


@freeze_time(NOW)
def test_the_feed_is_the_flight_now(client: Client, fr24: dict[str, Any]) -> None:
    """The feed sends the state and the card, cacheable for a moment."""
    item = ShareFactory.create()
    response = client.get(reverse("shares:feed", args=[item.token]))
    data = response.json()
    assert data["state"] == "live"
    assert data["flight"]["position"] == {"lat": 53.90511, "lon": -8.71522}
    assert data["checked"].startswith("2026-11-26T09:32")
    assert response["Cache-Control"] == "public, max-age=15"


@freeze_time(NOW)
def test_one_address_is_limited(client: Client, fr24: dict[str, Any], settings: Any) -> None:
    """Past a family's worth of tabs a minute, one address waits."""
    item = ShareFactory.create()
    url = reverse("shares:feed", args=[item.token])
    codes = [client.get(url).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60
    assert codes[60] == 429
    assert client.get(page_of(item)).status_code == 429


@freeze_time(NOW)
def test_the_preview_is_a_picture(client: Client, fr24: dict[str, Any]) -> None:
    """1200 by 630, PNG, and drawn once for a while."""
    item = ShareFactory.create()
    response = client.get(reverse("shares:preview", args=[item.token]))
    assert response["Content-Type"] == "image/png"
    assert Image.open(io.BytesIO(response.content)).size == (1200, 630)
    assert response["Cache-Control"] == "public, max-age=600"


@pytest.mark.parametrize(
    ("state", "card", "words"),
    [
        (shares.LIVE, SHARE_CARD, ("In the air", "5 h 4 m to go · lands 11:04")),
        (shares.LANDED, SHARE_CARD | {"status": "landed"}, ("Landed", "at JFK at 11:04")),
        (shares.ENDED, SHARE_CARD, ("Link ended", "This share link has stopped")),
        (
            shares.LIVE,
            SHARE_CARD | {"minutes_to_go": None, "arrives_local": None},
            ("In the air", ""),
        ),
    ],
)
def test_the_preview_says_the_state(
    state: str, card: dict[str, Any], words: tuple[str, str]
) -> None:
    """The picture's status line, for each state."""
    assert preview.status_line(state, card) == words
    assert preview.render(state, card)[:8] == b"\x89PNG\r\n\x1a\n"


@freeze_time(NOW)
def test_share_from_the_following_list_opens_the_link(
    signed_in: Client, user: Any, fr24: dict[str, Any]
) -> None:
    """The Following list's Share makes the link and goes to it."""
    response = signed_in.post(reverse("shares:create"), {"flight": "BA117"})
    item = Share.objects.get(user=user)
    assert response.status_code == 302
    assert response["Location"] == page_of(item)


@freeze_time(NOW)
def test_the_following_list_offers_share_for_a_flight_in_the_air(
    signed_in: Client, user: Any, fr24: dict[str, Any]
) -> None:
    """A flight in the air in the Following list has a Share button."""
    FollowFactory.create(user=user, fr24_id="42bc74bd", took_off_at=NOW - timedelta(hours=1))
    content = signed_in.get(reverse("flights:home")).content.decode()
    assert reverse("shares:create") in content
    assert 'aria-label="Share a live link to BA117"' in content


@pytest.mark.parametrize(
    ("flight", "problem"),
    [("hello", "That isn't a flight number"), ("EI154", "isn't in the air or just landed")],
)
def test_a_share_that_cant_be_made_says_why(
    signed_in: Client, fr24: dict[str, Any], flight: str, problem: str
) -> None:
    """The home page comes back with the reason."""
    response = signed_in.post(reverse("shares:create"), {"flight": flight})
    assert response.status_code == 400
    assert problem in html.unescape(response.content.decode())


def test_share_without_live_data_says_so(signed_in: Client, settings: Any) -> None:
    """No Flightradar24 key: the reason is the connection, not the flight."""
    settings.FR24_API_KEY = ""
    response = signed_in.post(reverse("shares:create"), {"flight": "BA117"})
    assert "Flightradar24 couldn't be reached" in html.unescape(response.content.decode())


def test_making_a_link_needs_an_account(client: Client, db: None) -> None:
    """Signed out, Share goes to sign in."""
    response = client.post(reverse("shares:create"), {"flight": "BA117"})
    assert response.status_code == 302
    assert reverse("accounts:sign_in") in response["Location"]


@freeze_time(NOW)
def test_the_account_page_lists_live_links_and_stops_them(
    signed_in: Client, user: Any, db: None
) -> None:
    """Sharing lists your live links; Stop sharing ends one at once."""
    mine = ShareFactory.create(user=user)
    ShareFactory.create(user=user, expires_at=NOW - timedelta(minutes=1))
    ShareFactory.create(user=UserFactory.create())
    content = signed_in.get(reverse("accounts:account")).content.decode()
    assert content.count("Stop sharing</button>") == 1
    assert shares.url(mine) in content
    response = signed_in.post(reverse("shares:stop", args=[mine.uuid]))
    assert response["Location"] == reverse("accounts:account") + "#sharing"
    assert not Share.objects.filter(pk=mine.pk).exists()
    assert "No live links." in signed_in.get(reverse("accounts:account")).content.decode()


def test_someone_elses_link_cant_be_stopped(signed_in: Client, db: None) -> None:
    """Stopping a link that isn't yours changes nothing."""
    theirs = ShareFactory.create()
    signed_in.post(reverse("shares:stop", args=[theirs.uuid]))
    assert Share.objects.filter(pk=theirs.pk).exists()


def test_deleting_the_account_deletes_its_links(user: Any) -> None:
    """A link belongs to its maker: it goes with the account."""
    ShareFactory.create(user=user)
    user.delete()
    assert not Share.objects.exists()


def test_the_feed_json_is_valid_in_the_page(client: Client, db: None) -> None:
    """The flight in the card's data-feed attribute is the feed's JSON, escaped as text."""
    item = ShareFactory.create(landed_at=NOW, snapshot=SHARE_CARD | {"status": "landed"})
    content = client.get(page_of(item)).content.decode()
    raw = re.search(r'data-feed="([^"]*)"', content)
    assert raw
    assert json.loads(html.unescape(raw.group(1)))["flight"]["flight"] == "BA117"
