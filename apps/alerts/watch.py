"""The watcher: notice take-offs and landings of followed flights, and send their alerts (RAS-144).

``watch_flights`` runs this every two minutes (a Render cron job). Each run
takes the follows whose next check has come, asks Flightradar24 for their
flight summaries (up to 15 flights a call), and for each follow:

- binds it to its leg, the first to take off at or after it was followed
  (or one still in the air then), the first time that leg shows up;
- sends the take-off alert when the leg's take-off time appears, and asks
  the live feed once for its ETA, so the alert can say when it lands;
- sends the landing alert when its landing time appears.

Each alert is recorded as sent, so a re-run never sends it twice. The run
writes back only the fields it owns (``WATCHED``), and only to follows that
still exist, so a channel turned off or a Stop pressed while it was asking
Flightradar24 holds; each alert reads the channels afresh before it goes. A follow
gives up after 24 hours without a take-off, or 20 hours in the air without
a landing. Checks thin out mid-flight: every 10 minutes while the ETA is
more than half an hour away, then every run.

Flightradar24 has no schedules or webhooks, so polling its summaries is the
only signal there is (docs/decisions/alerts-poll-flight-summaries.md).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from django.utils import timezone

from apps.alerts import notify
from apps.alerts.models import WAIT_FOR_LANDING, WAIT_FOR_TAKE_OFF, Follow
from apps.flights.fr24 import BATCH, LIVE, SUMMARY, Fr24Api, matches
from apps.flights.lookup import CALLSIGN, code_of, when

logger = logging.getLogger(__name__)

# Mid-flight, while the ETA is further off than NEAR_ETA, a follow is checked this often.
CRUISE_CHECK = timedelta(minutes=10)
NEAR_ETA = timedelta(minutes=30)
# How far before a follow's not_before its leg's summary may start (first seen before take-off).
WINDOW_SLACK = timedelta(hours=2)

# The fields the watcher sets. Everything else (the channels) is the person's.
WATCHED = (
    "fr24_id",
    "origin",
    "destination",
    "aircraft",
    "took_off_at",
    "arrives_at",
    "landed_at",
    "took_off_sent_at",
    "ended_at",
    "next_check_at",
)

TAKE_OFF = "take_off"
LANDING = "landing"


@dataclass
class Run:
    """What one run of the watcher found and did."""

    checked: int = 0
    calls: int = 0
    events: list[tuple[Follow, str]] = field(default_factory=list)
    ended: list[Follow] = field(default_factory=list)


def watch(
    api: Fr24Api,
    now: datetime | None = None,
    commit: bool = True,
    say: Callable[[str], None] = lambda text: None,
) -> Run:
    """Check every follow that's due, and (with ``commit``) save and send what's new."""
    moment = now or timezone.now()
    run = Run()
    due = list(Follow.objects.due(moment).select_related("user"))
    live = []
    for item in due:
        if give_up(item, moment):
            run.ended.append(item)
            say(f"{item.to_string()}: giving up ({item.state})")
        else:
            live.append(item)
    run.checked = len(live)
    for batch in batches(live):
        rows = summaries(api, batch, moment)
        for item in batch:
            for event in update(item, [r for r in rows if matches(item.flight, r)], moment):
                run.events.append((item, event))
                say(f"{item.to_string()}: {event.replace('_', ' ')}")
    took_off = [item for item, event in run.events if event == TAKE_OFF]
    if took_off:
        add_etas(api, took_off)
    for item in live:
        item.next_check_at = next_check(item, moment)
    run.calls = api.calls
    if not commit:
        return run
    gone = {item.pk for item in [*run.ended, *live] if not save(item, moment)}
    for item, event in run.events:
        if item.pk in gone:
            continue
        fresh = Follow.objects.filter(pk=item.pk).values("push", "email").first()
        if fresh is None:
            say(f"{item.to_string()}: stopped while checking, no alert")
            continue
        item.push, item.email = fresh["push"], fresh["email"]
        notify.send(item, event, moment)
    return run


def save(item: Follow, now: datetime) -> bool:
    """Write the watcher's fields of ``item`` to its row; False if the row has been deleted."""
    fields = {name: getattr(item, name) for name in WATCHED}
    updated = Follow.objects.filter(pk=item.pk).update(**fields, updated_at=now)
    if not updated:
        logger.info("alerts.watch %s was stopped mid-run: not saved", item.to_string())
    return bool(updated)


def give_up(item: Follow, now: datetime) -> bool:
    """End ``item`` if it waited too long for a take-off or a landing; return whether it did."""
    if (item.took_off_at is None and now - item.not_before > WAIT_FOR_TAKE_OFF) or (
        item.took_off_at is not None and now - item.took_off_at > WAIT_FOR_LANDING
    ):
        item.ended_at = now
    return item.ended_at is not None


def batches(follows: list[Follow]) -> list[list[Follow]]:
    """Return ``follows`` in groups one summary call can ask about: one kind, BATCH numbers."""
    groups: list[list[Follow]] = []
    for is_callsign in (False, True):
        kind = [f for f in follows if bool(CALLSIGN.match(f.flight)) is is_callsign]
        numbers = sorted({f.flight for f in kind})
        for start in range(0, len(numbers), BATCH):
            chunk = set(numbers[start : start + BATCH])
            groups.append([f for f in kind if f.flight in chunk])
    return groups


def summaries(api: Fr24Api, batch: list[Follow], now: datetime) -> list[dict[str, Any]]:
    """Ask Flightradar24 for the summaries of every flight in ``batch`` since it was followed."""
    by = "callsigns" if CALLSIGN.match(batch[0].flight) else "flights"
    since = min(f.took_off_at or f.not_before for f in batch) - WINDOW_SLACK
    return api.get(
        SUMMARY,
        {
            by: ",".join(sorted({f.flight for f in batch})),
            "flight_datetime_from": utc(since),
            "flight_datetime_to": utc(now),
        },
    )


def utc(moment: datetime) -> str:
    """Return ``moment`` as Flightradar24 takes a time: UTC, to the second, no zone."""
    return str(moment.astimezone(UTC).replace(microsecond=0, tzinfo=None))


def update(item: Follow, rows: list[dict[str, Any]], now: datetime) -> list[str]:
    """Apply ``rows`` (this flight's summaries) to ``item``; return the alerts now due."""
    row = leg(item, rows)
    if row is None:
        return []
    events = []
    took_off = when(row.get("datetime_takeoff"))
    landed = when(row.get("datetime_landed"))
    if not item.fr24_id:
        item.fr24_id = str(row.get("fr24_id") or "")
        item.origin = code_of(row, "orig")
        item.destination = code_of(row, "dest")
        item.aircraft = str(row.get("type") or "")
        if took_off and took_off < item.not_before:
            # In the air before it was followed: no take-off to tell anyone about.
            item.took_off_sent_at = item.not_before
    if took_off and item.took_off_at is None:
        item.took_off_at = took_off
    if landed and item.landed_at is None:
        item.landed_at = landed
        item.destination = str(
            row.get("dest_iata_actual") or row.get("dest_icao_actual") or item.destination
        )
    if item.took_off_at and item.took_off_sent_at is None:
        if item.landed_at:
            # Landed before we saw it take off (the watcher wasn't running): only the landing.
            item.took_off_sent_at = now
        else:
            events.append(TAKE_OFF)
    if item.landed_at and item.landed_sent_at is None:
        events.append(LANDING)
    return events


def leg(item: Follow, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the summary of ``item``'s leg: its bound leg, or the first one it can be."""
    if item.fr24_id:
        return next((r for r in rows if r.get("fr24_id") == item.fr24_id), None)
    candidates = []
    for row in rows:
        took_off = when(row.get("datetime_takeoff"))
        if took_off is None:
            continue
        landed = when(row.get("datetime_landed"))
        ended = bool(row.get("flight_ended"))
        still_flying_then = landed is None and not ended
        if (
            took_off >= item.not_before
            or still_flying_then
            or (landed and landed > item.not_before)
        ):
            candidates.append((took_off, row))
    return min(candidates, key=lambda c: c[0])[1] if candidates else None


def add_etas(api: Fr24Api, follows: list[Follow]) -> None:
    """Ask the live feed for the ETA of each flight that just took off (one call per batch)."""
    for batch in batches(follows):
        by = "callsigns" if CALLSIGN.match(batch[0].flight) else "flights"
        rows = api.get(LIVE, {by: ",".join(sorted({f.flight for f in batch}))})
        for item in batch:
            row = next((r for r in rows if r.get("fr24_id") == item.fr24_id), None)
            if row is not None:
                item.arrives_at = when(row.get("eta"))


def next_check(item: Follow, now: datetime) -> datetime | None:
    """Return when ``item`` is next checked: None means every run."""
    if item.landed_at or not item.took_off_at or not item.arrives_at:
        return None
    if item.arrives_at - now > NEAR_ETA + CRUISE_CHECK:
        return now + CRUISE_CHECK
    return None
