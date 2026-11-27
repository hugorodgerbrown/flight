// Tests for static/js/share.js: the share page's card, fed to flight_map.js and kept live (RAS-145).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const FLIGHT = {
  flight: 'BA117',
  status: 'airborne',
  origin: { code: 'LHR', name: 'London Heathrow', lat: 51.47, lon: -0.46, tz: 'Europe/London' },
  destination: { code: 'JFK', name: 'John F Kennedy', lat: 40.64, lon: -73.78, tz: 'America/New_York' },
  departed_local: '08:36',
  arrives_local: '13:41',
  minutes_to_go: 152,
  progress: 0.63,
  position: { lat: 54.0, lon: -56.5 },
  altitude_ft: 37000,
  seen: '2026-11-26T12:00:00Z',
};
const NOW = Date.parse('2026-11-26T12:00:20Z');

function page(state, flight) {
  const feed = JSON.stringify({ state, flight, checked: '2026-11-26T12:00:20Z' });
  document.body.innerHTML = `
    <p class="share-live" data-share-live></p>
    <article data-share data-card data-feed-url="/f/t/live.json" data-poll-seconds="30" data-state="${state}">
      <p data-summary></p>
      <svg class="flight-map" data-map viewBox="0 0 640 360"></svg>
      <p data-route></p><span class="status status--airborne" data-pill></span>
      <progress class="progress" max="100" value="0" data-progress></progress>
      <p><span data-departed></span><strong data-arrives></strong></p>
      <p data-note></p><p data-status hidden></p>
    </article>`;
  document.querySelector('[data-share]').dataset.feed = feed;
}

async function load(state = 'live', flight = FLIGHT) {
  page(state, flight);
  self.FlightLand = 'M0 0L10 0L10 10Z';
  vi.resetModules();
  await import('../../static/js/share.js');
  await import('../../static/js/flight_map.js');
  document.dispatchEvent(new Event('DOMContentLoaded'));
}

const q = (name) => document.querySelector(`[data-${name}]`);

// Each load adds its listeners to the one document; take them off after each test.
const added = [];
const addListener = document.addEventListener.bind(document);

beforeEach(() => {
  vi.spyOn(document, 'addEventListener').mockImplementation((type, listener, options) => {
    added.push([type, listener]);
    addListener(type, listener, options);
  });
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'Date'] });
  vi.setSystemTime(NOW);
  globalThis.fetch = vi.fn();
});

afterEach(() => {
  for (const [type, listener] of added.splice(0)) document.removeEventListener(type, listener);
  vi.restoreAllMocks();
  vi.clearAllTimers();
  vi.useRealTimers();
  delete self.McpApp;
  delete self.FlightMap;
  delete self.FlightLand;
  delete self.FlightShare;
  delete globalThis.fetch;
});

describe('the share page', () => {
  it('draws the flight it loaded with, and says it is live', async () => {
    await load();
    expect(q('summary').textContent).toBe('BA117 lands at John F Kennedy in 2 h 32 m.');
    expect(q('route').textContent).toBe('LHR → JFK');
    expect(q('map').querySelector('.flight-map__plane')).not.toBeNull();
    expect(q('progress').value).toBe(63);
    expect(q('share-live').textContent).toBe('Live · updated 20 seconds ago');
    expect(q('share-live').classList.contains('share-live--on')).toBe(true);
  });

  it('asks the feed every 30 seconds and moves the plane on', async () => {
    await load();
    const moved = { ...FLIGHT, progress: 0.7, seen: '2026-11-26T12:00:45Z' };
    fetch.mockResolvedValue({ ok: true, json: async () => ({ state: 'live', flight: moved }) });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetch).toHaveBeenCalledWith('/f/t/live.json', { headers: { Accept: 'application/json' } });
    expect(q('progress').value).toBe(70);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('stops asking once the flight has landed', async () => {
    await load();
    const landed = { ...FLIGHT, status: 'landed', progress: 1, position: null };
    fetch.mockResolvedValue({ ok: true, json: async () => ({ state: 'landed', flight: landed }) });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(q('share-live').textContent).toBe('Landed');
    expect(q('pill').classList.contains('status--landed')).toBe(true);
    expect(q('pill').classList.contains('status--airborne')).toBe(false);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('keeps the card and tries again when the feed fails', async () => {
    await load();
    fetch.mockRejectedValueOnce(new Error('offline'));
    await vi.advanceTimersByTimeAsync(30_000);
    expect(q('summary').textContent).toContain('lands at John F Kennedy');
    fetch.mockResolvedValue({ ok: false });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('does not ask while the tab is hidden, and catches up when it comes back', async () => {
    await load();
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetch).not.toHaveBeenCalled();
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
    fetch.mockResolvedValue({ ok: true, json: async () => ({ state: 'live', flight: FLIGHT }) });
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('shows an ended link as ended, without asking', async () => {
    await load('ended');
    expect(q('share-live').textContent).toBe('This link has ended');
    expect(q('pill').textContent).toBe('Ended');
    expect(q('pill').classList.contains('status--ended')).toBe(true);
    expect(q('summary').textContent).toBe('This link to BA117 has ended.');
    expect(q('arrives').textContent).toBe('');
    expect(q('map').querySelector('.flight-map__plane')).toBeNull();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('ends the card when the link has gone', async () => {
    await load();
    fetch.mockResolvedValue({ ok: false, status: 404 });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(q('share-live').textContent).toBe('This link has ended');
    expect(q('summary').textContent).toBe('This link to BA117 has ended.');
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('keeps the words it was served with when the flight in the page is unreadable', async () => {
    page('live', FLIGHT);
    document.querySelector('[data-share]').dataset.feed = '{not json';
    q('summary').textContent = 'Served words';
    vi.resetModules();
    await import('../../static/js/share.js');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    expect(q('summary').textContent).toBe('Served words');
  });

  it('says how long ago Flightradar24 heard from the plane', async () => {
    await load();
    const { ago } = self.FlightShare;
    expect([ago(3_000), ago(42_000), ago(70_000), ago(300_000)]).toEqual([
      'just now',
      '42 seconds ago',
      'a minute ago',
      '5 minutes ago',
    ]);
  });
});

describe('without a share card', () => {
  it('does nothing', async () => {
    document.body.innerHTML = '<p>Another page</p>';
    vi.resetModules();
    await import('../../static/js/share.js');
    expect(self.McpApp).toBeUndefined();
  });
});
