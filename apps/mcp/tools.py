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

from apps.flights import lookup
from apps.public.pages import page_as_markdown


class ToolError(Exception):
    """A problem with the call that the model can fix and retry."""


@dataclass(frozen=True)
class Tool:
    """One MCP tool: its name, description, input schema and implementation."""

    name: str
    description: str
    input_schema: dict[str, Any]
    func: Callable[[Any, dict[str, Any]], dict[str, Any]]
    read_only: bool = True
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
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {"readOnlyHint": self.read_only},
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
            text += f" It took off at {left} local time."
        if due:
            minutes = flight["minutes_to_go"]
            text += f" It's due at {due} local time, in {_duration(minutes)}."
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
            + (f" at {due} local time" if due else "")
            + f", from {_airport(origin)}."
            + (f" It took off at {left} local time." if left else "")
            + " The map shows the route it flew."
        )
    else:
        text = (
            f"Flightradar24 isn't giving a position for {number} right now, and doesn't say "
            f"why. Its latest flight took off from {_airport(origin)}"
            + (f" at {left} local time" if left else "")
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
            markdown=True,
            ui="ui://flight/map-v6",
        ),
        Tool(
            name="privacy_policy",
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
            description="The terms of service for using the app.",
            input_schema=NO_ARGUMENTS,
            func=terms_of_service,
            markdown=True,
        ),
        Tool(
            name="help",
            description=(
                "How to use the app: signing in, passkeys, installing it and using it offline."
            ),
            input_schema=NO_ARGUMENTS,
            func=help_page,
            markdown=True,
        ),
    ]
}
