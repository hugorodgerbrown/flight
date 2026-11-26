"""Tests for following flights from the app home, the push endpoints and the email stop link."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.alerts.models import Follow, PushSubscription
from apps.alerts.notify import stop_token
from apps.alerts.views import device_name
from tests.alerts.conftest import PUBLIC_KEY
from tests.factories import FollowFactory, PushSubscriptionFactory, UserFactory

HOME = "/app/"


@pytest.mark.django_db
def test_the_home_page_offers_to_follow_a_flight(signed_in: Client) -> None:
    """With nothing followed, the form and the empty state; no push banner without keys."""
    content = signed_in.get(HOME).content.decode()
    assert "<h2>Follow a flight</h2>" in content
    assert f'action="{reverse("alerts:follow")}"' in content
    assert "Follow a flight to hear when it takes off and lands." in content
    assert "data-push" not in content


@pytest.mark.django_db
def test_following_a_flight_lists_it(signed_in: Client, fr24: dict[str, Any], user: Any) -> None:
    """A flight not yet flying is followed and waits; following it again doesn't double it."""
    response = signed_in.post(reverse("alerts:follow"), {"flight": " ba 117 "})
    assert response.status_code == 302
    assert response["Location"] == "/app/#following"
    signed_in.post(reverse("alerts:follow"), {"flight": "BA117"})
    (item,) = Follow.objects.all()
    assert (item.user, item.flight, item.state) == (user, "BA117", "waiting")
    content = signed_in.get(HOME).content.decode()
    assert '<span class="flight__number">BA117</span>' in content
    assert "Waiting to take off" in content
    assert "We&#x27;ll tell you when it takes off." in content


@pytest.mark.django_db
def test_a_bad_flight_number_says_what_one_looks_like(signed_in: Client) -> None:
    """The form comes back with its error, and nothing is followed."""
    response = signed_in.post(reverse("alerts:follow"), {"flight": "to New York"})
    assert response.status_code == 400
    content = response.content.decode()
    assert "Enter a flight number, such as BA117 or EZY8812." in content
    assert 'aria-invalid="true"' in content
    assert not Follow.objects.exists()


@pytest.mark.django_db
def test_a_flight_in_the_air_shows_its_route_progress_and_times(
    signed_in: Client, user: Any
) -> None:
    """The row says where it's going and when it lands, with a progress bar from the clock."""
    now = timezone.now()
    FollowFactory.create(
        user=user,
        origin="LHR",
        destination="JFK",
        took_off_at=now - timedelta(hours=2),
        arrives_at=now + timedelta(hours=6),
    )
    content = signed_in.get(HOME).content.decode()
    assert "London (LHR) → New York (JFK)" in content
    assert '<progress class="progress" max="1" value="0.25"' in content
    assert "In the air" in content
    assert "lands about" in content
    assert "(in 6 h" in content


@pytest.mark.django_db
def test_landed_and_given_up_flights_say_so_then_clear(signed_in: Client, user: Any) -> None:
    """A finished flight stays a day with no toggles, then leaves the list."""
    now = timezone.now()
    FollowFactory.create(
        user=user,
        flight="LH903",
        origin="FRA",
        destination="LHR",
        took_off_at=now - timedelta(hours=2),
        landed_at=now - timedelta(minutes=30),
    )
    FollowFactory.create(user=user, flight="QF1", ended_at=now - timedelta(hours=1))
    FollowFactory.create(user=user, flight="EI154", landed_at=now - timedelta(days=2))
    content = signed_in.get(HOME).content.decode()
    assert "Landed" in content
    assert "1 h 30 m after take-off. Clears tomorrow." in content
    assert "It didn&#x27;t take off within a day, so we stopped following it." in content
    assert "EI154" not in content
    assert 'name="channel"' not in content


@pytest.mark.django_db
def test_someone_elses_follows_are_not_shown_or_changed(signed_in: Client) -> None:
    """Rows, toggles and stop are scoped to the signed-in account."""
    other = FollowFactory.create(user=UserFactory.create(), flight="EZY8812")
    assert "EZY8812" not in signed_in.get(HOME).content.decode()
    assert (
        signed_in.post(reverse("alerts:toggle", args=[other.uuid]), {"channel": "push"}).status_code
        == 404
    )
    assert signed_in.post(reverse("alerts:stop_following", args=[other.uuid])).status_code == 404
    other.refresh_from_db()
    assert other.push


@pytest.mark.django_db
def test_channels_toggle_and_stop_removes(signed_in: Client, user: Any) -> None:
    """Push and Email turn on and off for one flight; Stop deletes it."""
    user.email = "pat@example.com"
    user.save()
    item = FollowFactory.create(user=user)
    content = signed_in.get(HOME).content.decode()
    assert 'value="push" aria-pressed="true"' in content
    assert 'value="email" aria-pressed="true"' in content
    signed_in.post(reverse("alerts:toggle", args=[item.uuid]), {"channel": "email"})
    item.refresh_from_db()
    assert item.push
    assert not item.email
    assert (
        signed_in.post(reverse("alerts:toggle", args=[item.uuid]), {"channel": "sms"}).status_code
        == 400
    )
    signed_in.post(reverse("alerts:stop_following", args=[item.uuid]))
    assert not Follow.objects.exists()


@pytest.mark.django_db
def test_without_an_address_email_is_off_and_says_why(signed_in: Client, user: Any) -> None:
    """An account from before addresses were kept can't have email alerts until it signs in."""
    user.email = ""
    user.save()
    FollowFactory.create(user=user, email=False)
    content = signed_in.get(HOME).content.decode()
    assert "Sign out and in again to get email alerts too." in content
    assert "disabled" in content


@pytest.mark.django_db
def test_the_push_banner_shows_with_the_key(signed_in: Client, pushes: list[Any]) -> None:
    """With VAPID keys set, the home page carries the banner and its key for alerts.js."""
    content = signed_in.get(HOME).content.decode()
    assert f'data-push-key="{PUBLIC_KEY}"' in content
    assert 'data-push-shown-in="off install"' in content
    assert "js/alerts" in content


@pytest.mark.django_db
def test_the_account_page_says_where_alerts_go(
    signed_in: Client, user: Any, pushes: list[Any]
) -> None:
    """The address, this browser's push control, and the browsers that get notifications."""
    user.email = "pat@example.com"
    user.save()
    PushSubscriptionFactory.create(user=user, device="Chrome on Mac")
    content = signed_in.get(reverse("accounts:account")).content.decode()
    assert "<h2>Alerts</h2>" in content
    assert "<strong>pat@example.com</strong>" in content
    assert 'data-push-shown-in="off on blocked install unsupported"' in content
    assert "Notifications go to Chrome on Mac." in content


@pytest.mark.django_db
def test_the_account_page_without_push_keys(signed_in: Client) -> None:
    """Without keys, push isn't offered, and the page says so."""
    content = signed_in.get(reverse("accounts:account")).content.decode()
    assert "Push notifications aren't set up yet." in content
    assert "pat" not in content


def post_json(client: Client, name: str, body: Any) -> Any:
    """POST ``body`` as JSON to the named URL."""
    return client.post(reverse(name), json.dumps(body), content_type="application/json")


@pytest.mark.django_db
def test_a_browser_subscribes_and_unsubscribes(signed_in: Client, user: Any) -> None:
    """The subscription is saved once (a repeat updates it) and deleted on turning off."""
    body = {
        "endpoint": "https://push.example.test/abc",
        "keys": {"p256dh": "key", "auth": "secret"},
    }
    agent = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Version/18.0 Mobile Safari/604.1"
    )
    response = signed_in.post(
        reverse("alerts:push_subscribe"),
        json.dumps(body),
        content_type="application/json",
        headers={"User-Agent": agent},
    )
    assert response.status_code == 201
    (subscription,) = PushSubscription.objects.all()
    assert (subscription.user, subscription.p256dh, subscription.auth) == (user, "key", "secret")
    assert subscription.to_string() == "Safari on iPhone"
    assert post_json(signed_in, "alerts:push_subscribe", body).status_code == 200
    assert PushSubscription.objects.count() == 1
    assert post_json(
        signed_in, "alerts:push_unsubscribe", {"endpoint": body["endpoint"]}
    ).json() == {"ok": True}
    assert not PushSubscription.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        {"endpoint": "http://push.example.test/abc", "keys": {"p256dh": "k", "auth": "a"}},
        {"endpoint": "https://push.example.test/abc", "keys": "nope"},
        {"endpoint": "https://push.example.test/abc"},
        ["not", "an", "object"],
    ],
)
def test_a_bad_subscription_is_refused(signed_in: Client, body: Any) -> None:
    """Only an https endpoint with both keys is kept."""
    assert post_json(signed_in, "alerts:push_subscribe", body).status_code == 400
    assert not PushSubscription.objects.exists()


@pytest.mark.django_db
def test_push_endpoints_need_a_signed_in_account(client: Client) -> None:
    """Signed out, they answer 401 JSON, not a redirect."""
    assert post_json(client, "alerts:push_subscribe", {}).status_code == 401
    assert client.post(reverse("alerts:follow"), {"flight": "BA117"}).status_code == 302
    assert not Follow.objects.exists()


@pytest.mark.parametrize(
    ("agent", "name"),
    [
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/131.0 Safari/537.36",
            "Chrome on Mac",
        ),
        ("Mozilla/5.0 (Windows NT 10.0) Chrome/131.0 Safari/537.36 Edg/131.0", "Edge on Windows"),
        ("Mozilla/5.0 (Linux; Android 14) Firefox/133.0", "Firefox on Android"),
        ("curl/8", "A browser"),
    ],
)
def test_device_names(agent: str, name: str) -> None:
    """A browser is named by its engine and its device, never the raw User-Agent."""
    assert device_name(agent) == name


@pytest.mark.django_db
def test_an_email_stop_link_asks_then_stops(client: Client) -> None:
    """GET asks (a link checker must not stop alerts); the page's form stops, signed out."""
    item = FollowFactory.create()
    url = reverse("alerts:stop", args=[stop_token(item)])
    response = client.get(url)
    assert response.status_code == 200
    assert "Stop alerts for BA117?" in response.content.decode()
    assert 'name="csrfmiddlewaretoken"' in response.content.decode()
    assert Follow.objects.exists()
    response = client.post(url)
    assert "Alerts for BA117 stopped" in response.content.decode()
    assert not Follow.objects.exists()
    assert "nothing to stop" in client.post(url).content.decode()
    assert client.get(url).status_code == 404


@pytest.mark.django_db
def test_a_forged_stop_link_stops_nothing(client: Client) -> None:
    """A token not signed by us names no follow."""
    FollowFactory.create()
    assert client.get(reverse("alerts:stop", args=["forged"])).status_code == 404
    client.post(reverse("alerts:stop", args=["forged"]))
    assert Follow.objects.exists()


def test_a_follows_progress_comes_from_the_clock() -> None:
    """Halfway through its flight time is 0.5; without times there's no progress."""
    took_off = datetime(2026, 11, 26, 8, 0, tzinfo=UTC)
    item = FollowFactory.build(took_off_at=took_off, arrives_at=took_off + timedelta(hours=2))
    assert item.progress(took_off + timedelta(hours=1)) == 0.5
    assert item.progress(took_off + timedelta(hours=3)) == 1.0
    assert FollowFactory.build().progress() is None
    item.arrives_at = took_off
    assert item.progress(took_off) is None


@pytest.mark.django_db
def test_deleting_the_account_deletes_its_follows_and_browsers(
    signed_in: Client, user: Any
) -> None:
    """Follows and push subscriptions go with the account (a cascade)."""
    from apps.accounts.deletion import delete_account

    FollowFactory.create(user=user)
    PushSubscriptionFactory.create(user=user)
    delete_account(user)
    assert not Follow.objects.exists()
    assert not PushSubscription.objects.exists()


@pytest.mark.django_db
def test_the_admin_lists_follows_and_browsers(client: Client) -> None:
    """Staff see both lists."""
    admin = UserFactory.create(is_staff=True, is_superuser=True)
    client.force_login(admin)
    FollowFactory.create()
    PushSubscriptionFactory.create()
    assert client.get(reverse("admin:alerts_follow_changelist")).status_code == 200
    assert client.get(reverse("admin:alerts_pushsubscription_changelist")).status_code == 200
