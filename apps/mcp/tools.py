"""The MCP tools. Each is a function of (user, arguments) returning JSON-able data.

Add a tool by writing a function and listing it in TOOLS with its JSON
Schema. Raise ToolError for a mistake the model should see and correct.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from django.urls import reverse

from apps.alerts import follows
from apps.alerts.models import Follow
from apps.alerts.templatetags.alerts import route as route_of
from apps.alerts.templatetags.alerts import status_label, times
from apps.flights import lookup
from apps.public.pages import page_as_markdown
from apps.pwa import conf
from apps.shares import shares


class ToolError(Exception):
    """A problem with the call that the model can fix and retry."""


@dataclass(frozen=True)
class Tool:
    """One MCP tool: its name, description, input schema and implementation."""

    name: str
    # A short human name, which clients show in place of ``name`` and which
    # Claude's connector directory requires of every tool.
    title: str
    description: str
    input_schema: dict[str, Any]
    func: Callable[[Any, dict[str, Any]], dict[str, Any]]
    read_only: bool = True
    # True for a tool that deletes something (unfollow); MCP's default is true,
    # so every other tool says false.
    destructive: bool = False
    # True for a tool that reaches outside this app (where_is asks
    # Flightradar24); false for one that answers from the app alone.
    open_world: bool = False
    # The result's "markdown" is the text content, so the caller gets the
    # document itself rather than JSON around it.
    markdown: bool = False
    # A ui:// resource in apps/mcp/resources.py that the client renders with
    # the result (an MCP App). The text content still goes to the model.
    ui: str | None = None

    def describe(self) -> dict[str, Any]:
        """Return the tool as tools/list lists it."""
        described: dict[str, Any] = {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "openWorldHint": self.open_world,
            },
        }
        if self.ui:
            # "ui/resourceUri" is the spec's older flat key, kept until every
            # client reads the nested one.
            described["_meta"] = {"ui": {"resourceUri": self.ui}, "ui/resourceUri": self.ui}
        return described


FLIGHT_NUMBER = re.compile(r"^(?:[A-Z]{2}|[A-Z]\d|\d[A-Z])[A-Z]?\d{1,4}[A-Z]?$")
# Said with every answer: Flightradar24 has no schedules, so no delay.
NO_SCHEDULE = (
    "Times are Flightradar24's: it tracks the aircraft, not the airline's schedule, so it "
    "can't say whether the flight is late."
)


def _duration(minutes: int) -> str:
    """Return ``minutes`` as "1 h 40 m", "2 h" or "25 m"."""
    hours, mins = divmod(minutes, 60)
    return (
        " ".join(
            part for part in (f"{hours} h" if hours else "", f"{mins} m" if mins else "") if part
        )
        or "0 m"
    )


def _clock(moment: str | None, tz: str) -> str | None:
    """Return the ISO time ``moment`` as HH:MM in the time zone ``tz``, or None."""
    if not moment:
        return None
    return str(datetime.fromisoformat(moment).astimezone(ZoneInfo(tz)).strftime("%H:%M"))


def _local(local: str, utc: str | None) -> str:
    """Return a local clock with its UTC one, "08:36 local time (07:36 UTC)" (RAS-150).

    Claude reads only the text and the server doesn't know the user's time
    zone, so the UTC clock lets Claude say the time in the user's own.
    """
    if not utc or utc == local:
        return f"{local} local time and UTC"
    return f"{local} local time ({utc} UTC)"


def _airport(place: dict[str, Any]) -> str:
    """Return an airport as "London Heathrow (LHR)"."""
    return f"{place['name']} ({place['code']})"


def where_is(user: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Return where a flight is now, from Flightradar24, with a map view."""
    number = re.sub(r"\s+", "", str(args.get("flight", ""))).upper()
    if not FLIGHT_NUMBER.match(number):
        raise ToolError("flight must be a flight number such as BA1234.")
    try:
        flight = lookup.where(number)
    except lookup.NotConnected:
        raise ToolError(
            f"Flight isn't connected to live flight data right now, so it can't say where "
            f"{number} is."
        ) from None
    except lookup.Unavailable as exc:
        raise ToolError(str(exc)) from None
    if flight is None:
        raise ToolError(
            f"Flightradar24 has no flight {number} in the air now or in the last 24 hours. "
            "It knows a flight by the number of the airline flying it, so if this is a "
            "codeshare (sold by one airline, flown by another), try the operating airline's "
            "number: it's on the booking or the airport's departures board."
        )
    origin, destination = flight["origin"], flight["destination"]
    left = _clock(flight["departed"], origin["tz"])
    due = _clock(flight["arrives"], destination["tz"])
    seen = _clock(flight.get("seen"), "UTC")
    left_at = _local(left, _clock(flight["departed"], "UTC")) if left else ""
    due_at = _local(due, _clock(flight["arrives"], "UTC")) if due else ""
    # Claude reads only this text, not the card, so it says everything the card shows,
    # and says where a position came from without guessing why one is missing (RAS-140).
    if flight["status"] == lookup.AIRBORNE:
        kind = flight.get("position_kind")
        where_now = f"{round(flight['progress'] * 100)}% of the way" + (
            f", at {flight['altitude_ft']:,} ft" if flight["altitude_ft"] else ""
        )
        text = f"{number} is in the air from {_airport(origin)} to {_airport(destination)}"
        if kind == lookup.LAST_SEEN:
            text += (
                f". Flightradar24's live feed isn't showing it, so this is the last position "
                f"it recorded{f', at {seen} UTC' if seen else ''}: {where_now}."
            )
        elif kind == lookup.ESTIMATED:
            text += (
                f". Flightradar24 estimates it's {where_now}: the aircraft is out of its "
                "receivers' range, so the position is worked out, not received."
            )
        else:
            text += f", {where_now}."
        if left:
            text += f" It took off at {left_at}."
        if due:
            minutes = flight["minutes_to_go"]
            text += f" It's due at {due_at}, in {_duration(minutes)}."
        else:
            text += " Flightradar24 has no arrival estimate for it right now."
        text += (
            " The map shows its route and that last position."
            if kind == lookup.LAST_SEEN
            else " The map shows its route and where it is now."
        )
    elif flight["status"] == lookup.LANDED:
        text = (
            f"{number} landed at {_airport(destination)}"
            + (f" at {due_at}" if due else "")
            + f", from {_airport(origin)}."
            + (f" It took off at {left_at}." if left else "")
            + " The map shows the route it flew."
        )
    else:
        text = (
            f"Flightradar24 isn't giving a position for {number} right now, and doesn't say "
            f"why. Its latest flight took off from {_airport(origin)}"
            + (f" at {left_at}" if left else "")
            + f" for {_airport(destination)} and hasn't been reported landed."
            + (f" Flightradar24 last heard from it at {seen} UTC." if seen else "")
            + " The map shows that route."
        )
    if flight["operated_as"] != number:
        text += f" Flightradar24 lists it as {flight['operated_as']}."
    return flight | {
        "markdown": f"{text}\n\n{NO_SCHEDULE}",
        "departed_local": left,
        "arrives_local": due,
        "seen_utc": seen,
    }


def _channels(item: Follow, user: Any) -> str:
    """Return how a follow's alerts are sent, in words: "push and email"."""
    ways = [w for w, on in (("push", item.push), ("email", item.email and user.email)) if on]
    return " and ".join(ways) or "no channel (both are off)"


def _describe(item: Follow) -> str:
    """Return one followed flight in words, as the Following list shows it."""
    route = f", {route_of(item)}" if item.origin else ""
    return f"{item.flight}{route}: {status_label(item).lower()}. {times(item)}"


def follow(user: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Follow a flight for the user, for its take-off and landing alerts (RAS-144)."""
    try:
        item, created = follows.follow(user, str(args.get("flight", "")))
    except follows.NotAFlightNumber:
        raise ToolError("flight must be a flight number such as BA1234.") from None
    channels = _channels(item, user)
    if item.state == "airborne":
        text = (
            f"{item.flight} is already in the air, so {pwa_name()} will tell the user by "
            f"{channels} when it lands."
        )
    else:
        text = (
            f"{pwa_name()} will tell the user by {channels} when {item.flight} next takes off "
            "and when it lands."
        )
    if not created:
        text = f"The user already follows {item.flight}. " + text
    if item.push and not user.push_subscriptions.exists():
        text += (
            " No device has push notifications turned on yet: the user can turn them on in "
            f"the {pwa_name()} app ({_app_url()})."
        )
    if not user.email:
        text += " Email alerts need the user to sign out and in again once."
    return {"markdown": text, "flight": item.flight, "state": item.state, "created": created}


def unfollow(user: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Stop following a flight: no more alerts for it."""
    try:
        deleted = follows.unfollow(user, str(args.get("flight", "")))
    except follows.NotAFlightNumber:
        raise ToolError("flight must be a flight number such as BA1234.") from None
    number = re.sub(r"\s+", "", str(args.get("flight", ""))).upper()
    text = (
        f"Stopped following {number}: no more alerts for it."
        if deleted
        else f"The user wasn't following {number}."
    )
    return {"markdown": text, "stopped": bool(deleted)}


def following(user: Any, args: dict[str, Any]) -> dict[str, Any]:
    """List the flights the user follows, with each one's state."""
    items = list(Follow.objects.for_user(user).shown())
    if not items:
        return {
            "markdown": "The user isn't following any flights. Use follow to start.",
            "flights": [],
        }
    lines = [f"- {_describe(item)} Alerts by {_channels(item, user)}." for item in items]
    return {
        "markdown": "Flights the user follows:\n\n" + "\n".join(lines),
        "flights": [{"flight": i.flight, "state": i.state} for i in items],
    }


def share_flight(user: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Make a live link to a flight that anyone can open, without signing in (RAS-145)."""
    try:
        item, created = shares.share(user, str(args.get("flight", "")))
    except follows.NotAFlightNumber:
        raise ToolError("flight must be a flight number such as BA1234.") from None
    except shares.NothingToShare as exc:
        raise ToolError(
            f"{exc} isn't in the air or landed in the last day, so there's no flight to share "
            "yet. A link can be made once it has taken off."
        ) from None
    except lookup.NotConnected:
        raise ToolError("Flight isn't connected to live flight data right now.") from None
    except lookup.Unavailable as exc:
        raise ToolError(str(exc)) from None
    link = shares.url(item)
    route = item.to_string()
    text = (
        f"Here's a live link to {route}: {link}\n\n"
        "Anyone with it can follow the flight on a map that moves on its own, without signing "
        "in, until a day after it lands. The user can stop it at any time from the Sharing "
        f"section of their account page ({settings.SITE_URL}{reverse('accounts:account')}#sharing)."
    )
    if not created:
        text = "The user already has a link to this flight, so it's the same one.\n\n" + text
    return {"markdown": text, "url": link, "flight": item.flight, "created": created}


def pwa_name() -> str:
    """Return the app's name."""
    return conf.APP_NAME


def _app_url() -> str:
    """Return the app home's public address."""
    return f"{settings.SITE_URL}{reverse('flights:home')}"


def privacy_policy(user: Any, args: dict[str, Any]) -> dict[str, str]:
    """Return the privacy notice: what is kept about the user, and why."""
    return page_as_markdown("privacy")


def terms_of_service(user: Any, args: dict[str, Any]) -> dict[str, str]:
    """Return the terms of service."""
    return page_as_markdown("terms")


def help_page(user: Any, args: dict[str, Any]) -> dict[str, str]:
    """Return the help: signing in, passkeys, installing, offline use."""
    return page_as_markdown("help")


NO_ARGUMENTS: dict[str, Any] = {"type": "object", "properties": {}}

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            name="where_is",
            title="Where is a flight",
            description=(
                "Where a flight is now, from Flightradar24's live data: in the air (route, "
                "position, altitude, progress and ETA), landed, or not found, shown on a map. "
                "Give the operating airline's flight number, such as BA1234."
            ),
            input_schema={
                "type": "object",
                "properties": {"flight": {"type": "string", "maxLength": 10}},
                "required": ["flight"],
            },
            func=where_is,
            open_world=True,
            markdown=True,
            ui="ui://flight/map-v8",
        ),
        Tool(
            name="follow",
            title="Follow a flight",
            description=(
                "Follow a flight for the signed-in user: Flight sends them an alert by push "
                "notification and/or email when it next takes off and when it lands (or only "
                "when it lands, if it's in the air now). Give the operating airline's flight "
                "number, such as BA1234."
            ),
            input_schema={
                "type": "object",
                "properties": {"flight": {"type": "string", "maxLength": 10}},
                "required": ["flight"],
            },
            func=follow,
            read_only=False,
            markdown=True,
        ),
        Tool(
            name="unfollow",
            title="Stop following a flight",
            description="Stop following a flight: no more take-off or landing alerts for it.",
            input_schema={
                "type": "object",
                "properties": {"flight": {"type": "string", "maxLength": 10}},
                "required": ["flight"],
            },
            func=unfollow,
            read_only=False,
            destructive=True,
            markdown=True,
        ),
        Tool(
            name="following",
            title="Flights followed",
            description=(
                "The flights the signed-in user follows for alerts, each waiting to take off, "
                "in the air (with take-off and arrival times) or landed."
            ),
            input_schema=NO_ARGUMENTS,
            func=following,
            markdown=True,
        ),
        Tool(
            name="share_flight",
            title="Share a live link to a flight",
            description=(
                "Make a live link to a flight in the air (or landed in the last day) that the "
                "signed-in user can send to anyone: it opens a map of the flight that moves on "
                "its own, without signing in, until a day after it lands. Give the operating "
                "airline's flight number, such as BA1234. Give the link to the user as it is."
            ),
            input_schema={
                "type": "object",
                "properties": {"flight": {"type": "string", "maxLength": 10}},
                "required": ["flight"],
            },
            func=share_flight,
            read_only=False,
            open_world=True,
            markdown=True,
        ),
        Tool(
            name="privacy_policy",
            title="Privacy notice",
            description=(
                "The privacy notice: what is kept about the user, why, and for how long. "
                "Use it for any question about privacy or personal data."
            ),
            input_schema=NO_ARGUMENTS,
            func=privacy_policy,
            markdown=True,
        ),
        Tool(
            name="terms_of_service",
            title="Terms of service",
            description="The terms of service for using the app.",
            input_schema=NO_ARGUMENTS,
            func=terms_of_service,
            markdown=True,
        ),
        Tool(
            name="help",
            title="Help",
            description=(
                "How to use the app: signing in, passkeys, installing it and using it offline."
            ),
            input_schema=NO_ARGUMENTS,
            func=help_page,
            markdown=True,
        ),
    ]
}
