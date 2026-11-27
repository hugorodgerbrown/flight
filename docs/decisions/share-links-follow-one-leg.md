# Share links follow one leg, and are deleted when they end

Status: accepted (2026-11-27, RAS-145)

## Context

Someone flying wants the people meeting them to watch the flight without an
account. A flight number names a different leg every day, so a link to
"BA117" would show tomorrow's flight to anyone opening yesterday's link.
Every viewer polling Flightradar24 would spend credits per tab, and the
privacy notice promises that a share link is deleted when it ends.

## Decision

- **One leg.** A `Share` holds the Flightradar24 `fr24_id` of the leg that
  was in the air (or just landed) when it was made. When the number's
  current leg is a different one, the link asks for its own leg's landing
  and shows that, never the new flight.
- **One lookup for every viewer.** The page and its feed read
  `lookup.where()`, cached for 60 seconds, so any number of viewers of any
  number of links to one flight cost one call a minute. A landed link asks
  nothing more. The feed is cacheable for 15 seconds.
- **The last card is kept.** Each lookup's card is saved as the link's
  snapshot, so a Flightradar24 outage or a dropped leg shows what was last
  known rather than an error.
- **Lifetime.** A day after landing, or two days after it was made if no
  landing is seen. Stopping deletes it at once; `watch_flights` deletes
  ended links every run. An old address gets a "This link has ended" page
  (404), and an open page turns itself to ended when its feed 404s.
- **Unguessable, unlisted, anonymous.** A 128-bit token, `noindex`, and
  the page doesn't say who shared it. Viewing is rate limited per address.
- **One card.** The page uses the same scripts as Claude's map view
  (`static/js/flight_map.js`), fed by `static/js/share.js` in place of the
  MCP bridge, so the two never drift.
- **A picture of its own.** Chats unfurl the link with a 1200×630 PNG drawn
  by Pillow, cached for ten minutes.

## Consequences

Pillow is a dependency. The MCP view's scripts moved to `static/`, and
`apps/mcp/resources.py` inlines them from there.
