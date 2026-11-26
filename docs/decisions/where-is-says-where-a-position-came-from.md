# where_is says where a position came from

Status: accepted (2026-11-26, RAS-140). Builds on
[where-is-answers-from-live-flightradar24-data.md](where-is-answers-from-live-flightradar24-data.md).

## Context

On its first real test, "where is BA117" answered "No live position" while
the flight was over the Atlantic. Claude then guessed that the plane was out
of range, which our answer never said. What Flightradar24 showed at the time:

- The live feed returned no row for BA117 by flight number, callsign or
  registration. It did return other planes over the ocean, marked
  `source: ESTIMATED`, so coverage wasn't the cause.
- The flight summary still had the leg in the air (`flight_ended: false`,
  `last_seen` two minutes earlier).
- `/flight-tracks?flight_id=<fr24_id>` had 319 points, the latest 40
  minutes old, on Explorer.

## Decision

- **A flight missing from the live feed but still in the air shows its
  track's latest point.** That happens only when the summary has no
  landing and `flight_ended` is false. The answer says it's the last
  position recorded and gives its time in UTC. The card's pill says
  "Last seen HH:MM UTC". This costs one more call, and only in this case.
- **An estimated position is said to be one.** When a live row's `source`
  is `ESTIMATED`, the text says Flightradar24 estimates the position, and
  the card says "Estimated position". This is the one place the answer
  mentions range, because the API itself says so.
- **No position means no reason.** If there's no live row and no track
  point, the answer says that Flightradar24 isn't giving a position and
  doesn't say why. It names when Flightradar24 last heard from the flight,
  so the model has facts in place of a gap to fill.
- **The card's URI is `ui://flight/map-v3`.**

## Consequences

- A last-seen position can be some minutes old, so it is always shown
  with its time. We don't dead-reckon a current position from speed and
  heading. That would be our own guess, so it is left for a later issue
  if it's wanted.
- A track 403 (a plan without tracks) or 404 falls back to "no position".
