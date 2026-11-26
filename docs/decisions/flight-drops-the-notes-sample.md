# Flight drops the template's notes sample

Date: 2026-11-26 (RAS-139)

## Decision

The Titan template ships `apps/notes` as its example offline feature, at
`/app/`. Flight removes it: the app, its JavaScript, CSS, tests and e2e
journey, and its table (`apps/flights/migrations/0003_drop_notes_table.py`).
`/app/` is now Flight's own home page (`flights:home`): how to ask Claude
about a flight, and the connector's address.

The outbox, the idempotency middleware and the service worker stay, as the
template keeps them for every app. Their server-side tests post to a
stand-in endpoint mounted only in tests (`tests/outbox_endpoint.py`), as a
real outbox endpoint would be.

## Why

Hugo asked for the site to make no mention of the template's notes. Flight
has nothing to write offline yet: a lookup needs the network, and saves
nothing. Keeping a feature nobody uses would confuse people and Claude
alike (docs/decisions/flight-offers-claude-no-note-tools.md already took
the MCP note tools out).

## Consequences

- The e2e journey for an offline write (`test_offline_write.py`) is gone
  with the notes it wrote. The first real offline write, such as following
  a flight, brings a journey back.
- `copier update` may offer the notes files again: decline them.
