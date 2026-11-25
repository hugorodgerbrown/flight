# Flight's live data comes from FlightAware AeroAPI

Status: accepted (2026-11-25, RAS-124)

## Context

Flight answers "where is BA1234?" with the flight's route, position,
progress and landing time. That needs a live flight data source, looked up
on demand, one flight at a time. Traction is unproven, so a fixed monthly
fee is a cost before anyone uses the app.

The two candidates were FlightAware AeroAPI and Flightradar24's API
(Explorer, about $9 a month). The plan compares them:
[Flight: product brief and plan](https://claude.ai/artifact/Vs6LPTnU1uP7LAmjNPeKCK).

## Decision

Start on AeroAPI's Personal tier. It charges per query, about $0.005 for
GET /flights/{ident}, and gives $5 of queries free each month, so light
personal use costs nothing. The key is `AEROAPI_KEY`, read through
python-decouple and set in Render's `flight` env group, never in source.

`manage.py aeroapi_check` measures what AeroAPI covers before we build on
it. It looks up 20 real flights (short-haul, long-haul and codeshares) and
reports, for each one, whether it was found, its status, times, delay and
live position, and what the run cost at the list price. AeroAPI's own
usage count lags 10 to 20 minutes, so `--usage` reads it later, for free. Without
`--commit` it spends nothing. It is a dev tool: the app doesn't call it.
The run's results are recorded on RAS-124.

## Consequences

- Personal allows 10 queries a minute and is for personal use only. That
  fits a locked MVP with a few users. Opening Flight to the public needs a
  commercial tier.
- A position may be a separate query (GET /flights/{id}/position), so a
  lookup of a flight in the air can cost two queries.
- If usage grows past the free $5, or AeroAPI's coverage falls short,
  Flightradar24 is the next option. Switching is a new decision that links
  this one.
