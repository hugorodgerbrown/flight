"""The share link's public page, its live feed and preview picture, and making and stopping links.

``/f/<token>/`` is public: whoever has the link sees the flight, signed in
or not, and it is never indexed. The page draws the card with
static/js/flight_map.js, and static/js/share.js moves it on from
``/f/<token>/live.json`` every 30 seconds while the page is open. Making a
link and stopping one need the signed-in owner.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe

from apps.alerts.follows import NotAFlightNumber
from apps.core.decorators import signed_in_user
from apps.core.ratelimit import client_ip, over_limit
from apps.core.shortcuts import render
from apps.flights import lookup
from apps.shares import preview, shares
from apps.shares.models import Share

logger = logging.getLogger(__name__)

# How often the page asks for the flight again; lookup.where caches for 60.
POLL_SECONDS = 30
# Page loads and feed polls one address may make a minute: one open page
# polls twice a minute, so this is a family's worth of tabs.
VIEWS_PER_MINUTE = 60
# How long a preview picture is kept, drawn, before it's drawn again.
PREVIEW_SECONDS = 10 * 60


def found(request: HttpRequest, token: str) -> Share:
    """Return the share with ``token``, or 404: it never existed, or it ended and was deleted."""
    return get_object_or_404(Share, token=token)


def limited(request: HttpRequest) -> bool:
    """Count one view of a share from this address; True once it's over the limit."""
    return over_limit("share-view", client_ip(request), limit=VIEWS_PER_MINUTE, window_seconds=60)


def place(end: dict[str, Any]) -> str:
    """Return an airport as the page names it: its city, else its code."""
    return str(end.get("city") or end.get("code") or "")


def headline(flight: dict[str, Any]) -> str:
    """Return "BA117, London to New York"."""
    return (
        f"{flight.get('flight', '')}, {place(flight['origin'])} to {place(flight['destination'])}"
    )


def described(state: str, flight: dict[str, Any]) -> str:
    """Return the state in one sentence, for the link's preview and the page without JavaScript."""
    number, to = flight.get("flight", ""), flight["destination"]["name"]
    if state == shares.ENDED:
        return f"This link to {number} has ended."
    if state == shares.LANDED or flight.get("status") == lookup.LANDED:
        when = flight.get("arrives_local")
        return f"{number} landed at {to}" + (f" at {when} local time." if when else ".")
    due = flight.get("arrives_local")
    return f"{number} is in the air to {to}" + (f", due at {due} local time." if due else ".")


def feed_data(shown: shares.Shown) -> dict[str, Any]:
    """Return what the feed sends: the state, the card, and when it was asked."""
    return {"state": shown.state, "flight": shown.flight, "checked": timezone.now().isoformat()}


@require_safe
def page(request: HttpRequest, token: str) -> HttpResponse:
    """The share link: the flight's card, live while it flies."""
    if limited(request):
        return HttpResponse("Too many requests. Try again in a minute.", status=429)
    item = Share.objects.filter(token=token).first()
    if item is None:
        # Ended links are deleted, so an old link lands here: say so kindly.
        return render(request, "shares/gone.html", status=404)
    shown = shares.current(item)
    flight = shown.flight
    response = render(
        request,
        "shares/page.html",
        {
            "share": item,
            "state": shown.state,
            "flight": flight,
            "headline": headline(flight),
            "description": described(shown.state, flight),
            "feed": json.dumps(feed_data(shown)),
            "feed_url": reverse("shares:feed", args=[token]),
            "poll_seconds": POLL_SECONDS,
            "preview_url": request.build_absolute_uri(reverse("shares:preview", args=[token])),
            "progress_percent": round(max(0.0, min(1.0, float(flight.get("progress") or 0))) * 100),
        },
    )
    # Whoever has the link may look; search engines may not list it.
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@require_safe
def feed(request: HttpRequest, token: str) -> HttpResponse:
    """The flight now, as JSON, for share.js to move the card on."""
    if limited(request):
        return JsonResponse({"error": "rate_limited"}, status=429)
    item = found(request, token)
    response = JsonResponse(feed_data(shares.current(item)))
    response["Cache-Control"] = f"public, max-age={POLL_SECONDS // 2}"
    response["X-Robots-Tag"] = "noindex"
    return response


@require_safe
def preview_png(request: HttpRequest, token: str) -> HttpResponse:
    """The picture a chat shows for the link (apps/shares/preview.py)."""
    item = found(request, token)
    shown = shares.current(item)
    flight = shown.flight
    key = f"shares:preview:{token}:{shown.state}:{flight.get('status')}:{flight.get('seen')}"
    picture = cache.get(key)
    if picture is None:
        picture = preview.render(shown.state, flight)
        cache.set(key, picture, PREVIEW_SECONDS)
    response = HttpResponse(picture, content_type="image/png")
    response["Cache-Control"] = f"public, max-age={PREVIEW_SECONDS}"
    response["X-Robots-Tag"] = "noindex"
    return response


@require_POST
@login_required
def create(request: HttpRequest) -> HttpResponse:
    """Make a link to the flight in the form (the Following list's Share), then open it.

    The button shows only for a flight in the air, so a failure is rare: the
    home page comes back with the reason above the list.
    """
    from apps.alerts.views import following_context
    from apps.flights.views import home_context

    text = str(request.POST.get("flight", ""))
    try:
        item, _ = shares.share(signed_in_user(request), text)
    except NotAFlightNumber:
        problem = "That isn't a flight number such as BA117."
    except shares.NothingToShare:
        problem = f"{text.upper()} isn't in the air or just landed, so there's no flight to share."
    except lookup.NotConnected, lookup.Unavailable:
        problem = (
            "Flightradar24 couldn't be reached, so the link wasn't made. Try again in a minute."
        )
    else:
        return redirect("shares:page", token=item.token)
    context = home_context() | following_context(request) | {"share_problem": problem}
    return render(request, "flights/home.html", context, status=400)


@require_POST
@login_required
def stop(request: HttpRequest, uuid: str) -> HttpResponse:
    """Stop one of your links at once: from now on it says the link has ended."""
    shares.stop(signed_in_user(request), uuid)
    return redirect(reverse("accounts:account") + "#sharing")


def account_context(request: HttpRequest) -> dict[str, Any]:
    """Return the account page's Sharing section: the links still live."""
    user = signed_in_user(request)
    return {"live_shares": list(Share.objects.for_user(user).live())}
