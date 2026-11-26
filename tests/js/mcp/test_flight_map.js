// Tests for apps/mcp/ui/flight_map.js: the projection, the crop and the card it draws.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const HTML = readFileSync(resolve(__dirname, '../../../apps/mcp/ui/flight_map.html'), 'utf8');

const FLIGHT = {
  flight: 'BA1234',
  status: 'airborne',
  origin: { code: 'LIS', name: 'Lisbon', lat: 38.7742, lon: -9.1342 },
  destination: { code: 'LHR', name: 'London Heathrow', lat: 51.47, lon: -0.4543 },
  departed_local: '15:00',
  arrives_local: '17:40',
  minutes_to_go: 100,
  progress: 0.375,
  position: { lat: 43.6, lon: -6.4 },
  altitude_ft: 36000,
};

let onResult;

async function load() {
  document.body.innerHTML = HTML.slice(HTML.indexOf('<body>') + 6, HTML.indexOf('</body>'));
  self.FlightLand = 'M0 0L10 0L10 10Z';
  self.McpApp = { onToolResult: (listener) => (onResult = listener) };
  vi.resetModules();
  await import('../../../apps/mcp/ui/flight_map.js');
}

beforeEach(load);

afterEach(() => {
  delete self.McpApp;
  delete self.FlightMap;
  delete self.FlightLand;
});

describe('flight map geometry', () => {
  it('projects like bin/make-land-map: x is longitude + 180, the equator below the top', () => {
    const [x, y] = self.FlightMap.project(0, 0);
    expect(x).toBe(180);
    expect(y).toBeGreaterThan(170);
    expect(self.FlightMap.project(-180, 89)[1]).toBeCloseTo(0, 6);
  });

  it('runs the great circle from one airport to the other', () => {
    const points = self.FlightMap.greatCircle(FLIGHT.origin, FLIGHT.destination, 1, 8);
    expect(points).toHaveLength(9);
    expect(points[0].lat).toBeCloseTo(FLIGHT.origin.lat, 4);
    expect(points[8].lon).toBeCloseTo(FLIGHT.destination.lon, 4);
    const same = self.FlightMap.greatCircle(FLIGHT.origin, FLIGHT.origin, 1, 2);
    expect(same.every((p) => p.lat === FLIGHT.origin.lat)).toBe(true);
  });

  it('crops to the route with padding, never closer than a few degrees', () => {
    const view = self.FlightMap.frame([[100, 50], [101, 50.5]]);
    expect(640 / view.scale).toBeGreaterThanOrEqual(8);
    expect(view.x).toBeLessThan(100);
    expect(view.y).toBeLessThan(50);
  });

  it('puts an airport code on the side away from the route', () => {
    // The route leaves straight up, so the code sits straight below.
    expect(self.FlightMap.labelAt([100, 100], [100, 50])).toEqual([100, 118]);
    // The route leaves to the right, so the code sits to the left.
    expect(self.FlightMap.labelAt([100, 100], [130, 100])).toEqual([82, 100]);
  });

  it('says durations as people do', () => {
    expect(self.FlightMap.duration(100)).toBe('1 h 40 m');
    expect(self.FlightMap.duration(120)).toBe('2 h');
    expect(self.FlightMap.duration(0)).toBe('0 m');
  });
});

describe('the route through the plane', () => {
  it('runs the line through a plane that is off the airports\' great circle', () => {
    // BA117 over the North Atlantic, well north of the LHR-JFK great circle.
    const flight = {
      ...FLIGHT,
      origin: { code: 'LHR', lat: 51.47, lon: -0.4543 },
      destination: { code: 'JFK', lat: 40.6398, lon: -73.7789 },
      position: { lat: 60.5, lon: -35.2 },
    };
    const [flown, ahead] = self.FlightMap.legs(flight);
    const close = (a, b) => Math.abs(a.lat - b.lat) < 1e-6 && Math.abs(a.lon - b.lon) < 1e-6;
    expect(close(flown[0], flight.origin)).toBe(true);
    expect(close(flown[flown.length - 1], flight.position)).toBe(true);
    expect(close(ahead[0], flight.position)).toBe(true);
    expect(close(ahead[ahead.length - 1], flight.destination)).toBe(true);
  });

  it('draws the real path flown from the track, then on from the plane', () => {
    const path = [
      [51.48, -0.5],
      [53.9, -8.7],
      [55.8, -14.2],
    ];
    const flight = { ...FLIGHT, path, position: { lat: 58.0, lon: -25.0 } };
    const [flown, ahead] = self.FlightMap.legs(flight);
    expect(flown.map((p) => [p.lat, p.lon])).toEqual([[38.7742, -9.1342], ...path, [58.0, -25.0]]);
    expect(ahead[0]).toEqual({ lat: 58.0, lon: -25.0 });
  });

  it('draws a landed flight\'s whole path and nothing ahead', () => {
    const path = [
      [39, -9],
      [45, -5],
    ];
    const [flown, ahead] = self.FlightMap.legs({ ...FLIGHT, status: 'landed', position: null, path });
    expect(flown.map((p) => [p.lat, p.lon])).toEqual([[38.7742, -9.1342], ...path, [51.47, -0.4543]]);
    expect(ahead).toEqual([]);
    onResult({ structuredContent: { ...FLIGHT, status: 'landed', position: null, path } });
    const svg = document.querySelector('[data-map]');
    expect(svg.querySelector('.ahead')).toBeNull();
    expect(svg.querySelectorAll('.code').length).toBe(2);
  });

  it('ignores a path that is too short or not numbers', () => {
    const [flown] = self.FlightMap.legs({ ...FLIGHT, path: [[1, 'x'], [2, 2]] });
    expect(flown.length).toBe(65);
  });

  it('draws the flown fraction of the airports\' great circle without a position', () => {
    const [flown, ahead] = self.FlightMap.legs({ ...FLIGHT, status: 'lost', position: null, progress: 0 });
    expect(flown).toEqual([]);
    expect(ahead.length).toBeGreaterThan(2);
  });
});

describe('flight map card', () => {
  it('draws a flight in the air: sentence, route, plane, height and ETA, all as text', () => {
    onResult({ structuredContent: { ...FLIGHT, flight: '<b>BA1234</b>' } });
    const q = (name) => document.querySelector(`[data-${name}]`);
    expect(q('card').hidden).toBe(false);
    expect(q('status').hidden).toBe(true);
    expect(q('summary').textContent).toBe('<b>BA1234</b> lands at London Heathrow in 1 h 40 m.');
    expect(q('summary').querySelector('b')).toBeNull();
    expect(q('route').textContent).toBe('LIS → LHR');
    expect(q('pill').textContent).toBe('In the air · 36,000 ft');
    expect(q('pill').dataset.tone).toBe('ok');
    expect(q('progress').style.width).toBe('38%');
    expect(q('departed').textContent).toBe('Took off 15:00');
    expect(q('arrives').textContent).toBe('Due 17:40');
    expect(q('note').textContent).toContain('no airline schedule, so no delays');
    const svg = q('map');
    expect(svg.querySelector('.land').getAttribute('d')).toBe('M0 0L10 0L10 10Z');
    expect(svg.querySelector('.flown')).not.toBeNull();
    expect(svg.querySelector('.plane')).not.toBeNull();
    const [lis, lhr] = svg.querySelectorAll('.code');
    expect([lis.textContent, lhr.textContent]).toEqual(['LIS', 'LHR']);
    // Lisbon is south of London: its code goes below the airport, London's above.
    const [from, to] = svg.querySelectorAll('.airport');
    expect(Number(lis.getAttribute('y'))).toBeGreaterThan(Number(from.getAttribute('cy')));
    expect(Number(lhr.getAttribute('y'))).toBeLessThan(Number(to.getAttribute('cy')));
  });

  it('shows a landed flight with the whole route flown and no plane', () => {
    onResult({ structuredContent: { ...FLIGHT, status: 'landed', progress: 1, position: null, arrives_local: '17:52' } });
    const q = (name) => document.querySelector(`[data-${name}]`);
    expect(q('summary').textContent).toBe('BA1234 landed at London Heathrow.');
    expect(q('pill').textContent).toBe('Landed');
    expect(q('pill').dataset.tone).toBe('muted');
    expect(q('arrives').textContent).toBe('Landed 17:52');
    expect(q('progress').style.width).toBe('100%');
    expect(q('map').querySelector('.plane')).toBeNull();
    expect(q('map').querySelector('.flown')).not.toBeNull();
  });

  it('shows a flight with no live position without a plane or a flown line', () => {
    onResult({ structuredContent: { ...FLIGHT, status: 'lost', progress: 0, position: null, departed_local: null, arrives_local: null } });
    const q = (name) => document.querySelector(`[data-${name}]`);
    expect(q('summary').textContent).toBe("Flightradar24 isn't giving a position for BA1234 right now.");
    expect(q('pill').textContent).toBe('No position');
    expect(q('departed').textContent).toBe('');
    expect(q('arrives').textContent).toBe('');
    expect(q('map').querySelector('.plane')).toBeNull();
    expect(q('map').querySelector('.flown')).toBeNull();
  });

  it('labels an estimated position', () => {
    onResult({ structuredContent: { ...FLIGHT, position_kind: 'estimated' } });
    const q = (name) => document.querySelector(`[data-${name}]`);
    expect(q('pill').textContent).toBe('Estimated position · 36,000 ft');
    expect(q('pill').dataset.tone).toBe('ok');
  });

  it('shows the last recorded position of a flight missing from the live feed, with its time', () => {
    onResult({ structuredContent: { ...FLIGHT, position_kind: 'last_seen', seen_utc: '10:05', minutes_to_go: null, arrives_local: null } });
    const q = (name) => document.querySelector(`[data-${name}]`);
    expect(q('summary').textContent).toBe('BA1234 is on its way to London Heathrow; the map shows its last recorded position.');
    expect(q('pill').textContent).toBe('Last seen 10:05 UTC · 36,000 ft');
    expect(q('pill').dataset.tone).toBe('muted');
    expect(q('map').querySelector('.plane')).not.toBeNull();
    expect(self.FlightMap.pillFor({ status: 'airborne', position_kind: 'last_seen' }).pill).toBe('Last seen');
  });

  it('says so when a flight in the air has no ETA yet', () => {
    onResult({ structuredContent: { ...FLIGHT, minutes_to_go: null, arrives_local: null, altitude_ft: null } });
    const q = (name) => document.querySelector(`[data-${name}]`);
    expect(q('summary').textContent).toBe('BA1234 is on its way to London Heathrow.');
    expect(q('pill').textContent).toBe('In the air');
    expect(q('arrives').textContent).toBe('No ETA yet');
  });

  it('treats a status it does not know as no live position', () => {
    onResult({ structuredContent: { ...FLIGHT, status: 'mystery', position: null, progress: 0 } });
    expect(document.querySelector('[data-pill]').textContent).toBe('No position');
  });

  it('shows a landed flight without a landing time as just landed', () => {
    onResult({ structuredContent: { ...FLIGHT, status: 'landed', arrives_local: null } });
    expect(document.querySelector('[data-arrives]').textContent).toBe('Landed');
  });

  it('shows the error text instead of a card', () => {
    onResult({ isError: true, content: [{ type: 'text', text: 'flight must be a flight number such as BA1234.' }] });
    expect(document.querySelector('[data-card]').hidden).toBe(true);
    expect(document.querySelector('[data-status]').textContent).toContain('flight number');
    onResult({ structuredContent: {} });
    expect(document.querySelector('[data-status]').textContent).toBe('Something went wrong.');
  });
});

describe('long-haul on a globe (RAS-143)', () => {
  const LHR = { code: 'LHR', name: 'London Heathrow', lat: 51.47, lon: -0.4543 };
  const JFK = { code: 'JFK', name: 'New York JFK', lat: 40.6398, lon: -73.7789 };
  const LONG = { ...FLIGHT, origin: LHR, destination: JFK, position: { lat: 59.5, lon: -37 }, path: [[51.47, -0.46], [55.8, -14.2], [59.5, -37]] };

  // Run the vendored script as the card does, a classic script with no
  // module system, so it sets self.d3.
  const D3 = readFileSync(resolve(__dirname, '../../../apps/mcp/ui/vendor/d3_geo.js'), 'utf8');
  function withGlobe() {
    new Function('exports', 'module', 'define', D3).call(self);
    expect(typeof self.d3.geoOrthographic).toBe('function');
  }

  afterEach(() => {
    delete self.d3;
  });

  it('puts a long-haul route on the globe and keeps a short hop flat', () => {
    withGlobe();
    expect(self.FlightMap.onGlobe(LONG)).toBe(true);
    expect(self.FlightMap.onGlobe(FLIGHT)).toBe(false);
  });

  it('keeps the flat map when the globe library is missing', () => {
    expect(self.FlightMap.onGlobe(LONG)).toBe(false);
  });

  it('draws the globe: sphere, graticule, land with holes, the route and the plane', () => {
    withGlobe();
    onResult({ structuredContent: LONG });
    const svg = document.querySelector('[data-map]');
    expect(svg.classList.contains('globe')).toBe(true);
    expect(svg.querySelector('.sphere').getAttribute('d')).toMatch(/^M/);
    expect(svg.querySelector('.graticule').getAttribute('d')).toMatch(/^M/);
    expect(svg.querySelector('.land').classList.contains('globe-land')).toBe(true);
    expect(svg.querySelector('.flown').getAttribute('d')).toMatch(/^M/);
    expect(svg.querySelector('.ahead').getAttribute('d')).toMatch(/^M/);
    const plane = svg.querySelector('.plane');
    for (const axis of ['cx', 'cy']) expect(Number.isFinite(Number(plane.getAttribute(axis)))).toBe(true);
    // A short hop afterwards goes back to the flat map.
    onResult({ structuredContent: FLIGHT });
    expect(svg.classList.contains('globe')).toBe(false);
    expect(svg.querySelector('.sphere')).toBeNull();
  });

  it('curves the way ahead on from the plane\'s heading into the destination', () => {
    const [flown, ahead] = self.FlightMap.legs(LONG);
    const plane = flown[flown.length - 1];
    expect(ahead[0]).toEqual(expect.objectContaining({ lat: plane.lat }));
    const end = ahead[ahead.length - 1];
    expect(end.lat).toBeCloseTo(JFK.lat, 6);
    expect(end.lon).toBeCloseTo(JFK.lon, 6);
    // It leaves the way the plane arrived (no kink), not straight for JFK.
    const turn = (a, b) => {
      const d = Math.abs(a - b) % (2 * Math.PI);
      return Math.min(d, 2 * Math.PI - d);
    };
    const arriving = self.FlightMap.bearing(plane, { lat: 55.8, lon: -14.2 }) + Math.PI;
    const leaving = self.FlightMap.bearing(plane, ahead[1]);
    const direct = self.FlightMap.bearing(plane, JFK);
    expect(turn(leaving, arriving)).toBeLessThan((2 * Math.PI) / 180);
    expect(turn(direct, arriving)).toBeGreaterThan((10 * Math.PI) / 180);
  });

  it('goes straight for the destination when the plane is heading away from it', () => {
    const plane = { lat: 50, lon: -20 };
    const away = self.FlightMap.curveAhead(plane, JFK, { lat: 50, lon: -25 });
    const direct = self.FlightMap.greatCircle(plane, JFK, 1, 64);
    expect(away).toEqual(direct);
    expect(self.FlightMap.curveAhead(plane, JFK, null)).toEqual(direct);
  });
});
