# Flight's live data comes from the Flightradar24 API

Status: accepted (2026-11-25, RAS-134). Supersedes
[flight-data-comes-from-aeroapi.md](flight-data-comes-from-aeroapi.md).

## Context

Flight answers "where is BA1234?" with the flight's route, position and
landing time, so it needs a live flight data source. We first chose
FlightAware AeroAPI's free Personal tier (RAS-124), but Hugo couldn't
register: the sign-up kept failing. The plan already named Flightradar24's
API as the alternative ([Flight: product brief and plan](https://claude.ai/artifact/Vs6LPTnU1uP7LAmjNPeKCK)).

## Decision

Use the Flightradar24 API. Its sign-up is self-serve, a sandbox key works
without a plan, and the Explorer plan (about $9 a month) costs little for a
locked MVP. The key is `FR24_API_KEY`, read through python-decouple and set
in Render's `flight` env group, never in source. The AeroAPI check and its
key are removed.

`manage.py fr24_check` measures what Flightradar24 covers before we build
on it. It asks for 20 real flights' live positions and their summaries
over the last day, 15 flights to a call, and reports each flight's route,
position, ETA, take-off and landing, and the credits Flightradar24 counted.
Without `--commit` it makes no calls. It is a dev tool: the app doesn't call
it. The run's results are recorded on RAS-134.

## Consequences

- Flightradar24 tracks aircraft. It gives actual take-off and landing times
  and a live ETA, but not airline schedules, so Flight can't show "12 min
  late" from it alone. The card shows the ETA instead, or schedules come
  from another source later.
- Plans are priced in monthly credits, so heavy use costs more. The check
  measures credits per lookup, so we can tell whether Explorer covers
  personal use.
- A sandbox key returns sample data. Coverage numbers come from a run with
  a paid key.
- Flightradar24 refuses Python's default User-Agent (`Python-urllib`) even
  with a good key, while curl gets through (RAS-136). Every call sends
  Flight's own User-Agent, and a 403 is reported apart from a refused key.
