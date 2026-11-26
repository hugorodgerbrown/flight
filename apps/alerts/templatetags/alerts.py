"""Template filters for the Following list: a follow's state, route and times in words."""

from __future__ import annotations

from django import template
from django.utils import timezone

from apps.alerts.models import Follow
from apps.alerts.notify import clock, duration, place

register = template.Library()

LABELS = {
    "waiting": "Waiting to take off",
    "airborne": "In the air",
    "landed": "Landed",
    "ended": "Stopped",
}


@register.filter
def status_label(item: Follow) -> str:
    """Return the follow's state as its tag says it."""
    return LABELS[item.state]


@register.filter
def route(item: Follow) -> str:
    """Return the route as "London (LHR) → New York (JFK)"."""
    return f"{place(item.origin).short} → {place(item.destination).short}"


@register.filter
def times(item: Follow) -> str:
    """Return the one line of times under a followed flight."""
    origin, destination = place(item.origin), place(item.destination)
    state = item.state
    if state == "waiting":
        return "We'll tell you when it takes off."
    if state == "airborne":
        line = f"Took off {clock(item.took_off_at, origin.tz)}"
        if item.arrives_at:
            line += f" · lands about {clock(item.arrives_at, destination.tz)} local"
            left = item.arrives_at - timezone.now()
            if left.total_seconds() > 60:
                line += f" (in {duration(timezone.now(), item.arrives_at)})"
        return line
    if state == "landed":
        line = f"Landed {clock(item.landed_at, destination.tz)} local"
        if item.took_off_at and item.landed_at:
            line += f", {duration(item.took_off_at, item.landed_at)} after take-off"
        return line + ". Clears tomorrow."
    if item.took_off_at:
        return "Flightradar24 never reported it landed, so we stopped following it."
    return "It didn't take off within a day, so we stopped following it."


@register.filter
def percent(value: float) -> str:
    """Return a fraction as "62%"."""
    return f"{round(value * 100)}%"
