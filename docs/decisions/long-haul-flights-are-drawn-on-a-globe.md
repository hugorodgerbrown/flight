# Long-haul flights are drawn on a globe

Status: accepted (2026-11-26, RAS-143). Builds on
[the-flight-map-draws-its-own-land.md](the-flight-map-draws-its-own-land.md)
and [the-card-draws-the-path-flown.md](the-card-draws-the-path-flown.md).

## Context

Hugo wanted "some sense of the curvature of the earth when looking at
long-haul flights". He was shown a globe zoomed to the route (A) and the
whole globe (B), and chose A. He also asked for the line ahead to curve on
from the plane, rather than run straight to the destination.

## Decision

- **A route longer than 3,000 km is drawn on an orthographic globe**,
  centred on the route's midpoint and fitted to the route. Lines of
  latitude and longitude, and the globe's edge where it falls inside the
  card, show the curvature. Shorter routes keep the flat Mercator map.
- **d3-geo 3.1.1 and d3-array 3.2.4 are vendored** in
  `static/vendor/d3_geo.js`. They are unmodified minified builds
  under the ISC licence (GeographicLib's part is MIT), about 55 KB, and
  inlined into the card like the rest of it, so the card still loads
  nothing over the network. d3 does what we would otherwise hand-write
  badly: clipping land at the horizon, and fitting the view.
- **The globe reuses the land in `flight_land.js`.** Its Mercator rings
  are turned back into longitude and latitude once, and each ring is
  wound as the smaller area it bounds. The path is filled even-odd, so
  holes such as the Caspian stay sea, with no second copy of the data.
  `vendor/` is excluded from semgrep, like `static/vendor`.
- **The way ahead curves.** It's a quadratic Bézier on the sphere, from
  the plane to the destination, whose control point lies along the
  plane's heading (from the track) for 40% of the distance to go. It
  falls back to the great circle when there's no heading, or when the
  plane is heading away from the destination. This holds on both maps.
- **The card's URI is `ui://flight/map-v6`.**

## Consequences

- The card is about 55 KB bigger.
- The curve ahead is a drawing, not a forecast: it shows the way on, not
  the route the flight will fly.
