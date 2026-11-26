/*
 * apps/mcp/ui/flight_map.js — draw where_is's result as a map card.
 *
 * A short hop is drawn on the land from flight_land.js (Web Mercator in
 * degrees: x = longitude + 180, y = 0 at 85 degrees north), cropped to the
 * route. A long-haul route (over LONG_HAUL_KM) is drawn on a globe instead
 * (RAS-143): an orthographic projection from d3_geo.js, centred on the
 * route and zoomed to it, with lines of latitude and longitude, so the
 * earth's curvature shows. The
 * path flown is solid: the real track from Flightradar24 when the result
 * has one (RAS-142), else a great circle, and it always runs through the
 * plane (RAS-141), since a plane on an ocean track can be hundreds of miles
 * off the shortest route. The way ahead is dashed, a great circle from the
 * plane to the destination. The way ahead curves on from the plane's
 * heading into the destination, so it reads as the flown line continued.
 * The plane is one accent dot.
 * Everything from the result goes in as text, never as markup.
 */
(function () {
  'use strict';

  const SVG = 'http://www.w3.org/2000/svg';
  const WIDTH = 640;
  const HEIGHT = 360;
  const MAX_LAT = 85;
  const MIN_SPAN = 8; // degrees across: a short hop is not zoomed in further
  const PAD = 0.25; // of the route's size, on every side
  const STEPS = 64;
  const LABEL_GAP = 18; // from an airport's centre to its code's centre
  const LONG_HAUL_KM = 3000;
  const EARTH_KM = 6371;
  // How far back along the track the plane's heading is judged from (radians, about 20 km).
  const HEADING_FROM = 20 / EARTH_KM;
  // How far the way ahead keeps the plane's heading before turning for the destination.
  const LEAD = 0.4;
  const PAD_X = 0.12; // of the card's width, either side of the route, on the globe
  const PAD_Y = 0.16; // of its height, above and below
  const rad = (d) => (d * Math.PI) / 180;
  const deg = (r) => (r * 180) / Math.PI;
  const mercator = (lat) => deg(Math.log(Math.tan(Math.PI / 4 + rad(lat) / 2)));
  const TOP = mercator(MAX_LAT);

  function project(lon, lat) {
    const clamped = Math.max(-MAX_LAT, Math.min(MAX_LAT, lat));
    return [lon + 180, TOP - mercator(clamped)];
  }

  // The angle in radians between two points ({lat, lon}) on the globe.
  function arc(a, b) {
    const [lat1, lon1, lat2, lon2] = [a.lat, a.lon, b.lat, b.lon].map(rad);
    return (
      2 *
      Math.asin(
        Math.min(1, Math.sqrt(Math.sin((lat2 - lat1) / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2))
      )
    );
  }

  // The point fraction f of the way along the great circle from a to b.
  function between(a, b, f) {
    const angle = arc(a, b);
    if (angle === 0) return { lat: a.lat, lon: a.lon };
    const [lat1, lon1, lat2, lon2] = [a.lat, a.lon, b.lat, b.lon].map(rad);
    const p = Math.sin((1 - f) * angle) / Math.sin(angle);
    const q = Math.sin(f * angle) / Math.sin(angle);
    const x = p * Math.cos(lat1) * Math.cos(lon1) + q * Math.cos(lat2) * Math.cos(lon2);
    const y = p * Math.cos(lat1) * Math.sin(lon1) + q * Math.cos(lat2) * Math.sin(lon2);
    const z = p * Math.sin(lat1) + q * Math.sin(lat2);
    return { lat: deg(Math.atan2(z, Math.hypot(x, y))), lon: deg(Math.atan2(y, x)) };
  }

  // Points along the great circle from a to b ({lat, lon}), fraction 0 to `upTo`.
  function greatCircle(a, b, upTo, steps) {
    const points = [];
    for (let i = 0; i <= steps; i++) points.push(between(a, b, (upTo * i) / steps));
    return points;
  }

  // The initial bearing from a to b, in radians clockwise from north.
  function bearing(a, b) {
    const [lat1, lon1, lat2, lon2] = [a.lat, a.lon, b.lat, b.lon].map(rad);
    const y = Math.sin(lon2 - lon1) * Math.cos(lat2);
    const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(lon2 - lon1);
    return Math.atan2(y, x);
  }

  // The point `angle` radians from p along `heading`.
  function travel(p, heading, angle) {
    const [lat1, lon1] = [rad(p.lat), rad(p.lon)];
    const lat2 = Math.asin(Math.sin(lat1) * Math.cos(angle) + Math.cos(lat1) * Math.sin(angle) * Math.cos(heading));
    const lon2 =
      lon1 + Math.atan2(Math.sin(heading) * Math.sin(angle) * Math.cos(lat1), Math.cos(angle) - Math.sin(lat1) * Math.sin(lat2));
    return { lat: deg(lat2), lon: ((deg(lon2) + 540) % 360) - 180 };
  }

  // The way ahead from the plane: a curve that leaves along the heading it
  // came on (from `behind` to the plane) and bends into the destination, a
  // quadratic Bézier on the sphere. Without a heading, or one pointing away
  // from the destination, it is the great circle.
  function curveAhead(plane, destination, behind) {
    const togo = arc(plane, destination);
    if (!behind || togo === 0) return greatCircle(plane, destination, 1, STEPS);
    // The heading on arrival at the plane: the bearing back to `behind`, reversed.
    const heading = bearing(plane, behind) + Math.PI;
    let turn = Math.abs(heading - bearing(plane, destination));
    turn = Math.min(turn, 2 * Math.PI - turn);
    if (turn > Math.PI / 2) return greatCircle(plane, destination, 1, STEPS);
    const control = travel(plane, heading, LEAD * togo);
    const points = [];
    for (let i = 0; i <= STEPS; i++) {
      const t = i / STEPS;
      points.push(between(between(plane, control, t), between(control, destination, t), t));
    }
    return points;
  }

  // The crop of the projected map that holds `points` ([x, y]), padded, at the card's aspect.
  function frame(points) {
    const xs = points.map((p) => p[0]);
    const ys = points.map((p) => p[1]);
    let [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const span = Math.max(x1 - x0, ((y1 - y0) * WIDTH) / HEIGHT, MIN_SPAN) * (1 + 2 * PAD);
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    const tall = (span * HEIGHT) / WIDTH;
    return { x: cx - span / 2, y: cy - tall / 2, scale: WIDTH / span };
  }

  function el(name, attrs) {
    const node = document.createElementNS(SVG, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, String(value));
    return node;
  }

  function line(points, view) {
    return points
      .map((p, i) => {
        const [x, y] = project(p.lon, p.lat);
        return `${i ? 'L' : 'M'}${((x - view.x) * view.scale).toFixed(1)} ${((y - view.y) * view.scale).toFixed(1)}`;
      })
      .join('');
  }

  // Where an airport's code goes: LABEL_GAP away from the airport, on the side
  // away from the route (which leaves towards `toward`), so the line never
  // runs through it. The code is centred on that point.
  function labelAt(airport, toward) {
    const dx = toward[0] - airport[0];
    const dy = toward[1] - airport[1];
    const length = Math.hypot(dx, dy) || 1;
    return [airport[0] - (dx / length) * LABEL_GAP, airport[1] - (dy / length) * LABEL_GAP];
  }

  // The lines to draw: [flown, ahead], each a list of {lat, lon}. The flown
  // line is the real path from Flightradar24's track when there is one
  // (RAS-142), else a great circle; either way it runs through the plane
  // (RAS-141). The way ahead curves on from the plane's heading (RAS-143).
  function legs(flight) {
    const { origin, destination } = flight;
    const path = (Array.isArray(flight.path) ? flight.path : [])
      .map((p) => ({ lat: Number(p[0]), lon: Number(p[1]) }))
      .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
    const tracked = path.length >= 2;
    if (flight.position && flight.status === 'airborne') {
      const plane = { lat: Number(flight.position.lat), lon: Number(flight.position.lon) };
      const flown = tracked ? [origin, ...path, plane] : greatCircle(origin, plane, 1, STEPS);
      const behind = [...flown].reverse().find((p) => arc(p, plane) > HEADING_FROM);
      return [flown, curveAhead(plane, destination, behind)];
    }
    if (flight.status === 'landed' && tracked) return [[origin, ...path, destination], []];
    const progress = Math.max(0, Math.min(1, Number(flight.progress) || 0));
    return [progress > 0 ? greatCircle(origin, destination, progress, STEPS) : [], greatCircle(origin, destination, 1, STEPS)];
  }

  // A long-haul route goes on the globe, when the globe's library is there.
  function onGlobe(flight) {
    const d3 = self.d3;
    return Boolean(d3 && d3.geoOrthographic) && arc(flight.origin, flight.destination) * EARTH_KM > LONG_HAUL_KM;
  }

  // The land from flight_land.js as rings of [lon, lat], each wound as the
  // smaller of the two areas it bounds, for d3; holes are rings too, and the
  // path's even-odd fill leaves them as sea. Worked out once.
  let globeLand = null;
  function landRings() {
    if (globeLand) return globeLand;
    const d3 = self.d3;
    const rings = String(self.FlightLand || '')
      .split('M')
      .filter(Boolean)
      .map((ring) =>
        ring
          .replace(/Z/g, '')
          .split('L')
          .map((pair) => pair.trim().split(/\s+/).map(Number))
          .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y))
          .map(([x, y]) => [x - 180, deg(2 * Math.atan(Math.exp(rad(TOP - y)))) - 90])
      )
      .filter((ring) => ring.length >= 4)
      .map((ring) => {
        const closed = [...ring, ring[0]];
        return d3.geoArea({ type: 'Polygon', coordinates: [closed] }) > 2 * Math.PI ? [closed.reverse()] : [closed];
      });
    globeLand = { type: 'MultiPolygon', coordinates: rings };
    return globeLand;
  }

  // How to draw on the globe: where a point lands, a line's path, and the
  // sphere, graticule and land beneath the route.
  function globeView(flight, route) {
    const d3 = self.d3;
    const { origin, destination } = flight;
    const middle = between(origin, destination, 0.5);
    const projection = d3.geoOrthographic().rotate([-middle.lon, -middle.lat]).precision(0.3);
    projection.fitExtent(
      [
        [WIDTH * PAD_X, HEIGHT * PAD_Y],
        [WIDTH * (1 - PAD_X), HEIGHT * (1 - PAD_Y)],
      ],
      { type: 'MultiPoint', coordinates: route.map((p) => [p.lon, p.lat]) }
    );
    const draw = d3.geoPath(projection);
    return {
      at: (p) => projection([p.lon, p.lat]),
      line: (points) => draw({ type: 'LineString', coordinates: points.map((p) => [p.lon, p.lat]) }) || '',
      base: [
        el('path', { class: 'sphere', d: draw({ type: 'Sphere' }) || '' }),
        el('path', { class: 'graticule', d: draw(d3.geoGraticule10()) || '' }),
        el('path', { class: 'land globe-land', d: draw(landRings()) || '' }),
      ],
    };
  }

  // How to draw on the flat map, cropped to the route.
  function flatView(route) {
    const view = frame(route.map((p) => project(p.lon, p.lat)));
    return {
      at: (p) => {
        const [x, y] = project(p.lon, p.lat);
        return [(x - view.x) * view.scale, (y - view.y) * view.scale];
      },
      line: (points) => line(points, view),
      base: [
        el('path', {
          class: 'land',
          d: self.FlightLand || '',
          transform: `translate(${(-view.x * view.scale).toFixed(2)} ${(-view.y * view.scale).toFixed(2)}) scale(${view.scale.toFixed(4)})`,
        }),
      ],
    };
  }

  function draw(svg, flight) {
    const { origin, destination } = flight;
    const [flown, ahead] = legs(flight);
    const route = [...flown, ...ahead];
    const globe = onGlobe(flight);
    const view = globe ? globeView(flight, route) : flatView(route);
    const at = view.at;
    svg.classList.toggle('globe', globe);
    const parts = [...view.base];
    if (ahead.length) parts.push(el('path', { class: 'ahead', d: view.line(ahead) }));
    if (flown.length) parts.push(el('path', { class: 'flown', d: view.line(flown) }));
    // Each code sits away from the line leaving its airport, judged from the
    // first point far enough along it (a track starts on the runway).
    const first = flown.length ? flown : ahead;
    const last = ahead.length ? ahead : flown;
    const ends = [
      [origin, first],
      [destination, [...last].reverse()],
    ];
    for (const [airport, leaving] of ends) {
      const [x, y] = at(airport);
      parts.push(el('circle', { class: 'airport', cx: x.toFixed(1), cy: y.toFixed(1), r: 4 }));
      const next = leaving.map(at).find(([px, py]) => Math.hypot(px - x, py - y) > LABEL_GAP) || at(leaving[1] || airport);
      const [lx, ly] = labelAt([x, y], next);
      const code = el('text', { class: 'code', x: lx.toFixed(1), y: ly.toFixed(1) });
      code.textContent = airport.code;
      parts.push(code);
    }
    if (flight.position && flight.status === 'airborne') {
      const [x, y] = at(flight.position);
      parts.push(el('circle', { class: 'halo', cx: x.toFixed(1), cy: y.toFixed(1), r: 13 }));
      parts.push(el('circle', { class: 'plane', cx: x.toFixed(1), cy: y.toFixed(1), r: 6 }));
    }
    svg.replaceChildren(...parts);
    svg.setAttribute('aria-label', `Map of ${flight.flight} from ${origin.name} to ${destination.name}`);
  }

  function duration(minutes) {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return [hours ? `${hours} h` : '', mins ? `${mins} m` : ''].filter(Boolean).join(' ') || '0 m';
  }

  // What the card says for each status: the pill, its tone and the sentence.
  const STATUS = {
    airborne: { pill: 'In the air', tone: 'ok' },
    landed: { pill: 'Landed', tone: 'muted' },
    lost: { pill: 'No position', tone: 'muted' },
  };

  // An airborne flight's pill says where its position came from (RAS-140).
  function pillFor(flight) {
    const status = STATUS[flight.status] || STATUS.lost;
    if (flight.status !== 'airborne') return status;
    if (flight.position_kind === 'estimated') return { pill: 'Estimated position', tone: 'ok' };
    if (flight.position_kind === 'last_seen') {
      return { pill: flight.seen_utc ? `Last seen ${flight.seen_utc} UTC` : 'Last seen', tone: 'muted' };
    }
    return status;
  }

  function sentence(flight) {
    const to = flight.destination.name;
    if (flight.status === 'landed') return `${flight.flight} landed at ${to}.`;
    if (flight.status !== 'airborne') return `Flightradar24 isn't giving a position for ${flight.flight} right now.`;
    if (flight.position_kind === 'last_seen') return `${flight.flight} is on its way to ${to}; the map shows its last recorded position.`;
    if (flight.minutes_to_go === null || flight.minutes_to_go === undefined) {
      return `${flight.flight} is on its way to ${to}.`;
    }
    return `${flight.flight} lands at ${to} in ${duration(Math.max(0, Number(flight.minutes_to_go) || 0))}.`;
  }

  function arrival(flight) {
    if (flight.status === 'landed') return flight.arrives_local ? `Landed ${flight.arrives_local}` : 'Landed';
    if (flight.status !== 'airborne') return '';
    return flight.arrives_local ? `Due ${flight.arrives_local}` : 'No ETA yet';
  }

  function fill(flight) {
    const q = (name) => document.querySelector(`[data-${name}]`);
    const status = pillFor(flight);
    q('summary').textContent = sentence(flight);
    q('route').textContent = `${flight.origin.code} → ${flight.destination.code}`;
    const pill = q('pill');
    const height = flight.status === 'airborne' && flight.altitude_ft ? ` · ${Number(flight.altitude_ft).toLocaleString('en-GB')} ft` : '';
    pill.textContent = `${status.pill}${height}`;
    pill.dataset.tone = status.tone;
    q('progress').style.width = `${Math.round(Math.max(0, Math.min(1, Number(flight.progress) || 0)) * 100)}%`;
    q('departed').textContent = flight.departed_local ? `Took off ${flight.departed_local}` : '';
    q('arrives').textContent = arrival(flight);
    q('note').textContent = 'Live from Flightradar24, which has no airline schedule, so no delays.';
    q('note').hidden = false;
    draw(q('map'), flight);
  }

  self.FlightMap = { project, greatCircle, frame, duration, labelAt, sentence, pillFor, legs, arc, bearing, curveAhead, onGlobe };

  if (!self.McpApp) return;
  const status = document.querySelector('[data-status]');
  const card = document.querySelector('[data-card]');
  self.McpApp.onToolResult((result) => {
    const flight = result.structuredContent;
    if (result.isError || !flight || !flight.origin || !flight.destination) {
      card.hidden = true;
      status.textContent = ((result.content || [])[0] || {}).text || 'Something went wrong.';
      status.hidden = false;
      return;
    }
    fill(flight);
    status.hidden = true;
    card.hidden = false;
  });
})();
