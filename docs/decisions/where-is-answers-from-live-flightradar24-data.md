# where_is answers from live Flightradar24 data

Status: accepted (2026-11-26, RAS-138). Builds on
[flight-data-comes-from-flightradar24.md](flight-data-comes-from-flightradar24.md).

## Context

The spike (RAS-125) answered every flight with one made-up flight. The
20-lookup check (RAS-134) showed Flightradar24 covers operating flight
numbers well, at about 4 to 5 credits a lookup, against Explorer's 60,000
a month.

## Decision

- `where_is` asks for the flight's live position and its flights over the
  last day, and joins them by leg (`fr24_id`). The answer is one of three:
  in the air, landed, or seen taking off but not now tracked. A number
  Flightradar24 doesn't have is a tool error that says why, with the
  codeshare tip.
- **ETA, not delay.** Flightradar24 tracks aircraft and has no airline
  schedules, so every answer says its times can't show lateness.
- **Airports are stored, not bundled.** Flights name airports only by code.
  Each new code is fetched once from `/static/airports/{code}/full` into
  `Airport`, so we hold only airports we've seen.
- **One client, two paces.** `apps/flights/fr24.py` is shared by the tool and
  `fr24_check`. The check paces its calls; a lookup someone is waiting on
  doesn't, and waits only 2 seconds before retrying a 429.
- **A lookup is cached for 60 seconds**, so a client asking twice doesn't
  spend twice.
- **The card's URI carries a version** (`ui://flight/map-v2`). Claude caches
  a view by URI, so a changed card needs a new URI to reach people without
  reconnecting the connector. Bump it whenever the card changes.

## Consequences

- A codeshare (marketing) number isn't found. Mapping codeshares needs
  another source.
- A flight with no route in Flightradar24 can't be mapped, and says so.
- Each lookup costs two calls, plus one per airport the first time it's seen.
