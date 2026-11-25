// Tests for apps/mcp/ui/flight_map.js: the projection, the crop and the card it draws.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const HTML = readFileSync(resolve(__dirname, '../../../apps/mcp/ui/flight_map.html'), 'utf8');

const FLIGHT = {
  flight: 'BA1234',
  sample: true,
  status: 'airborne',
  delay_minutes: 12,
  origin: { code: 'LIS', name: 'Lisbon', lat: 38.7742, lon: -9.1342 },
  destination: { code: 'LHR', name: 'London Heathrow', lat: 51.47, lon: -0.4543 },
  departed_local: '15:00',
  arrives_local: '17:40',
  minutes_to_go: 100,
  progress: 0.375,
  position: { lat: 43.6, lon: -6.4 },
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

  it('says durations as people do', () => {
    expect(self.FlightMap.duration(100)).toBe('1 h 40 m');
    expect(self.FlightMap.duration(120)).toBe('2 h');
    expect(self.FlightMap.duration(0)).toBe('0 m');
  });
});

describe('flight map card', () => {
  it('draws the flight: sentence, route, plane, delay and times, all as text', () => {
    onResult({ structuredContent: { ...FLIGHT, flight: '<b>BA1234</b>' } });
    const q = (name) => document.querySelector(`[data-${name}]`);
    expect(q('card').hidden).toBe(false);
    expect(q('status').hidden).toBe(true);
    expect(q('summary').textContent).toBe('<b>BA1234</b> lands at London Heathrow in 1 h 40 m.');
    expect(q('summary').querySelector('b')).toBeNull();
    expect(q('route').textContent).toBe('LIS → LHR');
    expect(q('pill').textContent).toBe('12 min late');
    expect(q('pill').dataset.tone).toBe('late');
    expect(q('progress').style.width).toBe('38%');
    expect(q('arrives').textContent).toBe('Lands 17:40');
    expect(q('note').hidden).toBe(false);
    const svg = q('map');
    expect(svg.querySelector('.land').getAttribute('d')).toBe('M0 0L10 0L10 10Z');
    expect(svg.querySelector('.flown')).not.toBeNull();
    expect(svg.querySelector('.plane')).not.toBeNull();
    expect([...svg.querySelectorAll('.code')].map((t) => t.textContent)).toEqual(['LIS', 'LHR']);
  });

  it('shows an on-time flight on the ground without a plane or a flown line', () => {
    onResult({ structuredContent: { ...FLIGHT, delay_minutes: 0, status: 'scheduled', progress: 0, sample: false } });
    const q = (name) => document.querySelector(`[data-${name}]`);
    expect(q('pill').textContent).toBe('On time');
    expect(q('map').querySelector('.plane')).toBeNull();
    expect(q('map').querySelector('.flown')).toBeNull();
    expect(q('note').hidden).toBe(true);
  });

  it('shows the error text instead of a card', () => {
    onResult({ isError: true, content: [{ type: 'text', text: 'flight must be a flight number such as BA1234.' }] });
    expect(document.querySelector('[data-card]').hidden).toBe(true);
    expect(document.querySelector('[data-status]').textContent).toContain('flight number');
    onResult({ structuredContent: {} });
    expect(document.querySelector('[data-status]').textContent).toBe('Something went wrong.');
  });
});
