// Unit tests for static/js/sw_core.js: the service worker's routing rules.
import { describe, expect, it } from 'vitest';

import '../../static/js/sw_core.js';

const core = self.SwCore;
const config = {
  prefix: 'app',
  version: 'v2',
  staticUrl: '/static/',
  scope: '/app/',
  workerUrl: '/app/sw.js',
  neverCache: ['/app/private/'],
};
const ORIGIN = 'https://example.test';
const route = (path, method = 'GET', origin = ORIGIN) =>
  core.route({ method }, new URL(path, origin), ORIGIN, config);
const res = ({ headers = {}, ...overrides } = {}) => ({
  ok: true,
  redirected: false,
  type: 'basic',
  ...overrides,
  headers: new Headers(headers),
});

describe('route', () => {
  it.each([
    ['/static/css/app.css', 'GET', ORIGIN, 'static'],
    ['/app/', 'GET', ORIGIN, 'page'],
    ['/app/partials/items/', 'GET', ORIGIN, 'page'],
    ['/app/new/', 'POST', ORIGIN, 'bypass'],
    ['/app/sw.js', 'GET', ORIGIN, 'bypass'],
    ['/app/private/thing', 'GET', ORIGIN, 'bypass'],
    ['/', 'GET', ORIGIN, 'bypass'],
    ['/signin/?next=/app/', 'GET', ORIGIN, 'bypass'],
    ['/admin/', 'GET', ORIGIN, 'bypass'],
    ['/application', 'GET', ORIGIN, 'bypass'],
    ['/x.js', 'GET', 'https://cdn.example', 'bypass'],
  ])('%s %s from %s is %s', (path, method, origin, expected) => {
    expect(route(path, method, origin)).toBe(expected);
  });
});

describe('caches', () => {
  it('names caches by prefix and version', () => {
    expect(core.cacheNames(config)).toEqual({ static: 'app-static-v2', pages: 'app-pages-v2' });
  });

  it('treats only this app\'s other versions as stale', () => {
    expect(core.isStaleCache('app-static-v1', config)).toBe(true);
    expect(core.isStaleCache('app-pages-v2', config)).toBe(false);
    expect(core.isStaleCache('someone-else-v1', config)).toBe(false);
  });
});

describe('isStorable', () => {
  it('stores plain successful same-origin responses', () => {
    expect(core.isStorable(res())).toBe(true);
  });

  it.each([
    ['an error', { ok: false }],
    ['a redirect', { redirected: true }],
    ['an opaque response', { type: 'opaque' }],
    ['no-store', { headers: { 'Cache-Control': 'private, no-store' } }],
  ])('refuses %s', (_, overrides) => {
    expect(core.isStorable(res(overrides))).toBe(false);
  });

  it('keeps a no-store page the server marks for offline use', () => {
    const headers = { 'Cache-Control': 'private, no-store', 'Offline-Copy': 'allowed' };
    expect(core.isStorable(res({ headers }))).toBe(true);
  });

  it('still refuses a marked page that failed or redirected', () => {
    const headers = { 'Cache-Control': 'private, no-store', 'Offline-Copy': 'allowed' };
    expect(core.isStorable(res({ headers, redirected: true }))).toBe(false);
    expect(core.isStorable(res({ headers, ok: false }))).toBe(false);
  });
});

describe('isSignedOut', () => {
  it.each([
    ['a redirect', { redirected: true }, true],
    ['a 401', { ok: false, status: 401 }, true],
    ['a 403', { ok: false, status: 403 }, true],
    ['a server error', { ok: false, status: 500 }, false],
    ['a plain page', { status: 200 }, false],
  ])('%s', (_, overrides, expected) => {
    expect(core.isSignedOut(res(overrides))).toBe(expected);
  });
});

describe('notificationFor (RAS-144)', () => {
  const config = { scope: '/app/', appName: 'Flight', icon: '/static/icons/icon-192.png' };

  it('shows an alert, opening its page in the app', () => {
    const shown = core.notificationFor(
      { title: 'BA117 has taken off', body: 'Left LHR at 11:42.', url: '/app/#following', tag: 't' },
      config
    );
    expect(shown.title).toBe('BA117 has taken off');
    expect(shown.options).toMatchObject({ body: 'Left LHR at 11:42.', tag: 't', data: { url: '/app/#following' } });
  });

  it('never opens a page outside the app', () => {
    const shown = core.notificationFor({ title: 'x', url: 'https://elsewhere.test/' }, config);
    expect(shown.options.data.url).toBe('/app/');
  });

  it('falls back to the app name for a message with nothing to show', () => {
    expect(core.notificationFor(null, config).title).toBe('Flight');
    expect(core.notificationFor({ title: 3 }, config).options.body).toBe('');
  });
});
