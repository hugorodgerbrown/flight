"""Following flights, from the app home and from emails (RAS-144).

- ``follow``, ``toggle`` and ``stop`` are plain form posts from the
  Following list on the app home (``flights:home``), so they work without
  JavaScript, and redirect back to it.
- ``push_subscribe`` and ``push_unsubscribe`` take JSON from
  ``static/js/alerts.js`` when a browser turns notifications on or off.
- ``email_stop`` is the stop link in every alert email: a signed token, so
  it works without signing in, and answers a one-click POST from mail apps.

None of these go through the outbox: following needs the network to be
worth anything (docs/decisions/alerts-poll-flight-summaries.md).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from apps.accounts.models import User
from apps.alerts import follows, push
from apps.alerts.forms import FollowForm
from apps.alerts.models import Follow, PushSubscription
from apps.alerts.notify import follow_for_token
from apps.core.decorators import login_required_json, signed_in_user
from apps.core.shortcuts import render
from apps.flights.views import home_context

logger = logging.getLogger(__name__)


def following_context(request: HttpRequest, form: FollowForm | None = None) -> dict[str, Any]:
    """Return what the Following list on the app home needs."""
    user = signed_in_user(request)
    items = list(Follow.objects.for_user(user).shown())
    now = timezone.now()
    return {
        "follow_form": form or FollowForm(),
        "following": [(item, item.progress(now)) for item in items],
        "has_email": bool(getattr(user, "email", "")),
        "push_key": push_key(),
    }


def account_context(request: HttpRequest) -> dict[str, Any]:
    """Return what the account page's Alerts section needs."""
    user = signed_in_user(request)
    devices = [s.to_string() for s in PushSubscription.objects.for_user(user)]
    return {"push_key": push_key(), "push_devices": devices}


def push_key() -> str:
    """Return the key browsers subscribe with, or an empty string when push is off."""
    return str(settings.WEBPUSH_PUBLIC_KEY) if push.enabled() else ""


def home_again(anchor: str = "following") -> HttpResponseRedirect:
    """Return a redirect to the app home's Following list."""
    return HttpResponseRedirect(f"{reverse('flights:home')}#{anchor}")


@require_POST
@login_required
def follow(request: HttpRequest) -> HttpResponse:
    """Follow the flight in the form, then show the list; a bad number shows the form's error."""
    form = FollowForm(request.POST)
    if not form.is_valid():
        context = home_context() | following_context(request, form)
        return render(request, "flights/home.html", context, status=400)
    follows.follow(signed_in_user(request), form.cleaned_data["flight"])
    return home_again()


@require_POST
@login_required
def toggle(request: HttpRequest, uuid: str) -> HttpResponse:
    """Turn one of a followed flight's channels (push or email) on or off."""
    item = get_object_or_404(Follow.objects.for_user(signed_in_user(request)), uuid=uuid)
    channel = request.POST.get("channel")
    if channel not in {"push", "email"}:
        return HttpResponseBadRequest("channel must be push or email.")
    setattr(item, channel, not getattr(item, channel))
    item.save(update_fields=[channel, "updated_at"])
    return home_again()


@require_POST
@login_required
def stop(request: HttpRequest, uuid: str) -> HttpResponse:
    """Stop following a flight: its alerts stop and it leaves the list."""
    item = get_object_or_404(Follow.objects.for_user(signed_in_user(request)), uuid=uuid)
    logger.info("alerts.stop %s", item.to_string())
    item.delete()
    return home_again()


def _json(request: HttpRequest) -> dict[str, Any] | None:
    """Return the request's JSON object body, or None."""
    try:
        body = json.loads(request.body)
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


@require_POST
@login_required_json
def push_subscribe(request: HttpRequest) -> JsonResponse:
    """Save this browser's push subscription (from PushManager.subscribe) for the account."""
    body = _json(request) or {}
    endpoint = str(body.get("endpoint") or "")
    keys = body.get("keys")
    if not isinstance(keys, dict):
        keys = {}
    p256dh, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
    if not endpoint.startswith("https://") or not p256dh or not auth or len(endpoint) > 1000:
        return JsonResponse({"error": "bad_subscription"}, status=400)
    user = signed_in_user(request)
    if not isinstance(user, User):
        raise PermissionDenied
    subscription, created = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": user,
            "p256dh": p256dh[:200],
            "auth": auth[:100],
            "device": device_name(request.headers.get("User-Agent", "")),
        },
    )
    logger.info("alerts.push_subscribe %s created=%s", subscription.to_string(), created)
    return JsonResponse({"ok": True}, status=201 if created else 200)


@require_POST
@login_required_json
def push_unsubscribe(request: HttpRequest) -> JsonResponse:
    """Forget this browser's push subscription."""
    endpoint = str((_json(request) or {}).get("endpoint") or "")
    PushSubscription.objects.for_user(signed_in_user(request)).filter(endpoint=endpoint).delete()
    return JsonResponse({"ok": True})


def device_name(agent: str) -> str:
    """Return a short name for a browser from its User-Agent, such as "Safari on iPhone"."""
    browser = next(
        (
            name
            for token, name in (
                ("Edg/", "Edge"),
                ("Firefox/", "Firefox"),
                ("Chrome/", "Chrome"),
                ("CriOS/", "Chrome"),
                ("Safari/", "Safari"),
            )
            if token in agent
        ),
        "A browser",
    )
    device = next(
        (
            name
            for token, name in (
                ("iPhone", "iPhone"),
                ("iPad", "iPad"),
                ("Android", "Android"),
                ("Mac OS X", "Mac"),
                ("Windows", "Windows"),
                ("Linux", "Linux"),
            )
            if token in agent
        ),
        "",
    )
    return f"{browser} on {device}" if device else browser


@csrf_exempt  # The signed token is the authority: a mail app's one-click POST has no CSRF token.
@require_http_methods(["GET", "POST"])
def email_stop(request: HttpRequest, token: str) -> HttpResponse:
    """An email's stop link: GET asks, POST stops that flight's alerts (RFC 8058 one-click)."""
    item = follow_for_token(token)
    if request.method == "POST":
        if item is not None:
            logger.info("alerts.email_stop %s", item.to_string())
            item.delete()
        return render(request, "alerts/stopped.html", {"flight": item.flight if item else ""})
    if item is None:
        return render(request, "alerts/stopped.html", {"flight": ""}, status=404)
    return render(request, "alerts/stop.html", {"item": item, "token": token})
