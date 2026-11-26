"""Sending a follow's alerts: the words, the email and the push notifications (RAS-144).

``send(follow, event)`` writes the alert once (``message``) and sends it by
each channel the follow has on: an email to the account's address, and a
Web Push notification to each of its browsers. The time it went is
recorded on the follow, so it is never sent twice, even when one channel
fails: an alert late or missing on one channel beats it repeated on all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from apps.alerts import push
from apps.alerts.models import Follow
from apps.flights.models import Airport
from apps.pwa import conf

logger = logging.getLogger(__name__)

STOP_SALT = "alerts.stop"


@dataclass(frozen=True)
class Place:
    """One end of a flight, as an alert names it."""

    code: str
    name: str
    city: str
    tz: str

    @property
    def label(self) -> str:
        """Return "London Heathrow Airport", or the bare code for an airport we don't know."""
        return self.name or self.code or "its destination"

    @property
    def short(self) -> str:
        """Return "London (LHR)": short enough for a notification and a list row."""
        if self.city and self.code:
            return f"{self.city} ({self.code})"
        return self.label


def place(code: str) -> Place:
    """Return the airport with ``code`` as an alert names it (UTC when we don't know it)."""
    airport = Airport.objects.with_code(code).first() if code else None
    if airport is None:
        return Place(code=code, name="", city="", tz="UTC")
    return Place(code=airport.code, name=airport.name, city=airport.city, tz=airport.tz)


def clock(moment: datetime | None, tz: str) -> str:
    """Return ``moment`` as HH:MM in ``tz``, or an empty string."""
    return moment.astimezone(ZoneInfo(tz)).strftime("%H:%M") if moment else ""


def duration(start: datetime, end: datetime) -> str:
    """Return the time between ``start`` and ``end`` as "8 h 15 m"."""
    hours, minutes = divmod(max(0, round((end - start).total_seconds() / 60)), 60)
    parts = (f"{hours} h" if hours else "", f"{minutes} m" if minutes or not hours else "")
    return " ".join(p for p in parts if p)


def stop_token(item: Follow) -> str:
    """Return the signed token in an email's stop link: it names the follow, nothing else."""
    return signing.dumps(str(item.uuid), salt=STOP_SALT, compress=True)


def follow_for_token(token: str) -> Follow | None:
    """Return the follow a stop link names, or None for a bad token or a deleted follow."""
    try:
        uuid = signing.loads(token, salt=STOP_SALT)
    except signing.BadSignature:
        return None
    return Follow.objects.filter(uuid=uuid).first()


def absolute(path: str) -> str:
    """Return ``path`` on the site's public address."""
    return urljoin(settings.SITE_URL, path)


def message(item: Follow, event: str) -> dict[str, str]:
    """Return the alert for ``event`` ("take_off" or "landing"): title, body and the rest."""
    origin, destination = place(item.origin), place(item.destination)
    if event == "take_off":
        title = f"{item.flight} has taken off"
        body = f"Left {origin.short} at {clock(item.took_off_at, origin.tz)}."
        due = clock(item.arrives_at, destination.tz)
        body += (
            f" Lands in {destination.short} about {due} local."
            if due
            else f" On its way to {destination.short}."
        )
        subject = f"{item.flight} has taken off from {origin.short}"
    else:
        title = f"{item.flight} has landed"
        body = f"Landed in {destination.short} at {clock(item.landed_at, destination.tz)} local"
        if item.took_off_at and item.landed_at:
            body += f", {duration(item.took_off_at, item.landed_at)} after take-off"
        body += "."
        subject = f"{item.flight} has landed in {destination.short}"
    return {
        "title": title,
        "body": body,
        "subject": subject,
        "url": reverse("flights:home"),
        "tag": f"{item.uuid}-{event}",
    }


def send(item: Follow, event: str, now: datetime | None = None) -> None:
    """Send ``item``'s ``event`` alert by its channels, and record that it went."""
    moment = now or timezone.now()
    words = message(item, event)
    if item.email and item.user.email:
        try:
            send_email(item, event, words)
        except Exception:
            logger.exception("alerts.email failed for %s %s", item.to_string(), event)
    if item.push:
        push.send_to_user(item.user, words)
    if event == "take_off":
        item.took_off_sent_at = moment
    else:
        item.landed_sent_at = moment
    item.save(update_fields=["took_off_sent_at", "landed_sent_at", "updated_at"])
    logger.info("alerts.sent %s %s", item.to_string(), event)


def send_email(item: Follow, event: str, words: dict[str, str]) -> None:
    """Email the alert to the account's address, as plain text and HTML, with a stop link."""
    origin, destination = place(item.origin), place(item.destination)
    stop_url = absolute(reverse("alerts:stop", args=[stop_token(item)]))
    context = {
        "item": item,
        "event": event,
        "words": words,
        "origin": origin,
        "destination": destination,
        "took_off": clock(item.took_off_at, origin.tz),
        "arrives": clock(item.arrives_at, destination.tz),
        "landed": clock(item.landed_at, destination.tz),
        "app_url": absolute(words["url"]),
        "stop_url": stop_url,
        "site_name": conf.APP_NAME,
        "brand_colour": conf.THEME_COLOUR,
    }
    mail = EmailMultiAlternatives(
        subject=words["subject"],
        body=render_to_string("alerts/emails/alert.txt", context),
        to=[item.user.email],
        # Mail apps show their own Unsubscribe button, which opens the stop page.
        headers={"List-Unsubscribe": f"<{stop_url}>"},
    )
    mail.attach_alternative(render_to_string("alerts/emails/alert.html", context), "text/html")
    mail.send()
