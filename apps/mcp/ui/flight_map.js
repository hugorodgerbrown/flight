/*
 * apps/mcp/ui/flight_map.js — draw where_is's result as a map card.
 *
 * The map is the land from flight_land.js (Web Mercator in degrees: x =
 * longitude + 180, y = 0 at 85 degrees north), cropped to the route. The
 * route is the great circle between the airports: flown part solid, the
 * rest dashed, the plane one accent dot. Everything from the result goes
 * in as text, never as markup.
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
  const rad = (d) => (d * Math.PI) / 180;
  const deg = (r) => (r * 180) / Math.PI;
  const mercator = (lat) => deg(Math.log(Math.tan(Math.PI / 4 + rad(lat) / 2)));
  const TOP = mercator(MAX_LAT);

  function project(lon, lat) {
    const clamped = Math.max(-MAX_LAT, Math.min(MAX_LAT, lat));
    return [lon + 180, TOP - mercator(clamped)];
  }

  // Points along the great circle from a to b ({lat, lon}), fraction 0 to `upTo`.
  function greatCircle(a, b, upTo, steps) {
    const [lat1, lon1, lat2, lon2] = [a.lat, a.lon, b.lat, b.lon].map(rad);
    const angle =
      2 *
      Math.asin(
        Math.sqrt(Math.sin((lat2 - lat1) / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin((lon2 - lon1) / 2) ** 2)
      );
    const points = [];
    for (let i = 0; i <= steps; i++) {
      const f = (upTo * i) / steps;
      if (angle === 0) {
        points.push({ lat: a.lat, lon: a.lon });
        continue;
      }
      const p = Math.sin((1 - f) * angle) / Math.sin(angle);
      const q = Math.sin(f * angle) / Math.sin(angle);
      const x = p * Math.cos(lat1) * Math.cos(lon1) + q * Math.cos(lat2) * Math.cos(lon2);
      const y = p * Math.cos(lat1) * Math.sin(lon1) + q * Math.cos(lat2) * Math.sin(lon2);
      const z = p * Math.sin(lat1) + q * Math.sin(lat2);
      points.push({ lat: deg(Math.atan2(z, Math.hypot(x, y))), lon: deg(Math.atan2(y, x)) });
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

  function draw(svg, flight) {
    const { origin, destination } = flight;
    const progress = Math.max(0, Math.min(1, Number(flight.progress) || 0));
    const route = greatCircle(origin, destination, 1, STEPS);
    const view = frame(route.map((p) => project(p.lon, p.lat)));
    const at = (p) => {
      const [x, y] = project(p.lon, p.lat);
      return [(x - view.x) * view.scale, (y - view.y) * view.scale];
    };

    const land = el('path', {
      class: 'land',
      d: self.FlightLand || '',
      transform: `translate(${(-view.x * view.scale).toFixed(2)} ${(-view.y * view.scale).toFixed(2)}) scale(${view.scale.toFixed(4)})`,
    });
    const parts = [land, el('path', { class: 'ahead', d: line(route, view) })];
    if (progress > 0) {
      parts.push(el('path', { class: 'flown', d: line(greatCircle(origin, destination, progress, STEPS), view) }));
    }
    const ends = [
      [origin, route[1]],
      [destination, route[STEPS - 1]],
    ];
    for (const [airport, next] of ends) {
      const [x, y] = at(airport);
      parts.push(el('circle', { class: 'airport', cx: x.toFixed(1), cy: y.toFixed(1), r: 4 }));
      const [lx, ly] = labelAt([x, y], at(next));
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

  self.FlightMap = { project, greatCircle, frame, duration, labelAt, sentence, pillFor };

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
