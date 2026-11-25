# The flight map draws its own land instead of loading map tiles

Status: accepted (2026-11-25)

## Context

Flight's core answer is a map card in Claude: ask "where is BA1234?" and
see the route, the plane and the landing time (RAS-125). The card is an MCP
App view, and views here load nothing over the network
([mcp-apps-are-self-contained-ui-resources.md](mcp-apps-are-self-contained-ui-resources.md)).
A tiled map (MapLibre with a tile server) would need the view to declare
`resourceDomains` and `connectDomains`, depend on a tile provider's terms,
availability and keys, and leak which part of the world a person is
looking at to that provider. The card needs very little of a map: land and
sea at the scale of one route, muted, with one accent plane.

## Decision

The view draws the map itself as SVG. `bin/make-land-map` turns Natural
Earth's 1:50m land (public domain, from the `world-atlas` npm package) into
one Web Mercator path in `apps/mcp/ui/flight_land.js`, simplified to about
160 KB. `flight_map.js` crops it to the route's great circle, padded and
never closer than 8 degrees across, and draws the route (flown part solid,
the rest dashed), the airports and the plane on top. Colours come from the
host's style variables, so it follows light and dark themes.

## Consequences

- The view keeps working with no network, needs no CSP domains, keys or
  tile provider, and tells no one where a person is looking.
- No streets, cities or labels beyond the airport codes. That suits a
  flight's scale; a short hop of under 8 degrees looks wide.
- The land file is generated: change it by re-running `bin/make-land-map`,
  never by hand. It is inlined into the view on every `resources/read`,
  which clients cache.
- If a later page needs a real zoomable map (an airport close-up), that is
  a new decision with its own provider, not a change to this card.
