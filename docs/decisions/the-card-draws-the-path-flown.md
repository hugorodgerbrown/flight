# The card draws the path flown

Status: accepted (2026-11-26, RAS-142). Builds on RAS-141, which drew the
line through the plane.

## Context

A long-haul flight flies the day's ocean tracks, not the shortest path, so
a great circle between the airports puts the plane off its line. RAS-141
fixed that with two great circles through the plane. Hugo asked for the
real path instead: "we have plenty of credits to play with and the UI is
the primary asset".

## Decision

- **Every lookup that finds a leg also fetches its track.** That's
  `/flight-tracks?flight_id=<fr24_id>`, which is on Explorer. The answer
  carries a `path` of `[lat, lon]` pairs, thinned to at most 200 points
  with the newest kept.
- **The card draws the path solid**, from the origin through the track
  to the plane, and dashes a great circle from the plane to the
  destination. A landed flight shows its whole path. With no track, it
  falls back to RAS-141's great circles.
- **The card's URI is `ui://flight/map-v5`.**

## Consequences

- A lookup is three calls instead of two, and costs more credits. That's
  still well within Explorer's 60,000 a month for personal use.
- The last-seen fallback (RAS-140) reuses the same track.
