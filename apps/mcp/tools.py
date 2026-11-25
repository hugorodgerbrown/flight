"""The MCP tools. Each is a function of (user, arguments) returning JSON-able data.

Add a tool by writing a function and listing it in TOOLS with its JSON
Schema. Raise ToolError for a mistake the model should see and correct.
"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.utils import timezone

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


# RAS-125 spike: one fixed flight, timed around now, so the map view can be
# tried in Claude before any flight data is wired in. Replaced in phase 1.
FLIGHT_NUMBER = re.compile(r"^(?:[A-Z]{2}|[A-Z]\d|\d[A-Z])[A-Z]?\d{1,4}[A-Z]?$")
SAMPLE_ORIGIN: dict[str, Any] = {
    "code": "LIS",
    "name": "Lisbon",
    "lat": 38.7742,
    "lon": -9.1342,
    "tz": "Europe/Lisbon",
}
SAMPLE_DESTINATION: dict[str, Any] = {
    "code": "LHR",
    "name": "London Heathrow",
    "lat": 51.47,
    "lon": -0.4543,
    "tz": "Europe/London",
}
SAMPLE_FLOWN = timedelta(minutes=60)
SAMPLE_TO_GO = timedelta(minutes=100)
SAMPLE_DELAY_MINUTES = 12


def great_circle(start: dict[str, Any], end: dict[str, Any], fraction: float) -> dict[str, float]:
    """Return the point ``fraction`` of the way along the great circle from start to end."""
    lat1, lon1, lat2, lon2 = map(math.radians, (start["lat"], start["lon"], end["lat"], end["lon"]))
    angle = 2 * math.asin(
        math.sqrt(
            math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
        )
    )
    a = math.sin((1 - fraction) * angle) / math.sin(angle)
    b = math.sin(fraction * angle) / math.sin(angle)
    x = a * math.cos(lat1) * math.cos(lon1) + b * math.cos(lat2) * math.cos(lon2)
    y = a * math.cos(lat1) * math.sin(lon1) + b * math.cos(lat2) * math.sin(lon2)
    z = a * math.sin(lat1) + b * math.sin(lat2)
    return {
        "lat": round(math.degrees(math.atan2(z, math.hypot(x, y))), 4),
        "lon": round(math.degrees(math.atan2(y, x)), 4),
    }


def _duration(minutes: int) -> str:
    """Return ``minutes`` as "1 h 40 m", "2 h" or "25 m"."""
    hours, mins = divmod(minutes, 60)
    return (
        " ".join(
            part for part in (f"{hours} h" if hours else "", f"{mins} m" if mins else "") if part
        )
        or "0 m"
    )


def _clock(moment: Any, tz: str) -> str:
    """Return ``moment`` as HH:MM in the time zone ``tz``."""
    return str(moment.astimezone(ZoneInfo(tz)).strftime("%H:%M"))


def where_is(user: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Return where a flight is now, with a map view (sample data for the spike)."""
    number = re.sub(r"\s+", "", str(args.get("flight", ""))).upper()
    if not FLIGHT_NUMBER.match(number):
        raise ToolError("flight must be a flight number such as BA1234.")
    now = timezone.now()
    departed, arrives = now - SAMPLE_FLOWN, now + SAMPLE_TO_GO
    progress = round(SAMPLE_FLOWN / (SAMPLE_FLOWN + SAMPLE_TO_GO), 3)
    to_go = int(SAMPLE_TO_GO.total_seconds() // 60)
    lands = _clock(arrives, SAMPLE_DESTINATION["tz"])
    left = _clock(departed, SAMPLE_ORIGIN["tz"])
    origin, destination = SAMPLE_ORIGIN, SAMPLE_DESTINATION
    # Claude reads only this text, not the card, so it says everything the card shows.
    summary = (
        f"{number} is in the air from {origin['name']} ({origin['code']}) to "
        f"{destination['name']} ({destination['code']}), {round(progress * 100)}% of the "
        f"way. It left at {left} local time and lands at {lands} local time, "
        f"in {_duration(to_go)}, {SAMPLE_DELAY_MINUTES} "
        "minutes late. The map shows its route and where it is now.\n\n"
        "This is sample data: Flight is not yet connected to live flights, so this "
        "is a made-up flight to show how an answer will look. Say so when you pass it on."
    )
    return {
        "markdown": summary,
        "sample": True,
        "flight": number,
        "status": "airborne",
        "delay_minutes": SAMPLE_DELAY_MINUTES,
        "origin": SAMPLE_ORIGIN,
        "destination": SAMPLE_DESTINATION,
        "departed": departed.isoformat(),
        "departed_local": left,
        "arrives": arrives.isoformat(),
        "arrives_local": lands,
        "minutes_to_go": to_go,
        "progress": progress,
        "position": great_circle(SAMPLE_ORIGIN, SAMPLE_DESTINATION, progress),
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
                "Where a flight is now: its route, position, progress and landing time, "
                "shown on a map. Give the flight number, such as BA1234."
            ),
            input_schema={
                "type": "object",
                "properties": {"flight": {"type": "string", "maxLength": 10}},
                "required": ["flight"],
            },
            func=where_is,
            markdown=True,
            ui="ui://flight/map",
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
