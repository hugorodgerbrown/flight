// Tests for static/js/sw_worker.js: a cached page never outlives a sign-out.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../static/js/idb.js';
import '../../static/js/outbox_core.js';
import '../../static/js/outbox.js';
import '../../static/js/sw_core.js';

const { AppDB } = self;
const stored = new Map();
let onMessage;
let onFetch;
let onPush;
let onNotificationClick;

beforeAll(async () => {
  self.SW_CONFIG = {
    prefix: 'app',
    version: 'v1',
    staticUrl: '/static/',
    scope: '/app/',
    workerUrl: '/app/sw.js',
    neverCache: [],
    precache: [],
    offlineUrl: '/app/offline/',
    appName: 'Flight',
    icon: '/static/icons/icon-192.png',
  };
  const add = vi.spyOn(self, 'addEventListener');
  await import('../../static/js/sw_worker.js');
  onMessage = add.mock.calls.find(([type]) => type === 'message')[1];
  onFetch = add.mock.calls.find(([type]) => type === 'fetch')[1];
  onPush = add.mock.calls.find(([type]) => type === 'push')[1];
  onNotificationClick = add.mock.calls.find(([type]) => type === 'notificationclick')[1];
  add.mockRestore();
});

beforeEach(async () => {
  stored.clear();
  vi.stubGlobal('caches', {
    open: async () => ({
      put: async (url, response) => stored.set(String(url.url ?? url), response),
      delete: async (url) => stored.delete(String(url.url ?? url)),
      match: async (url) => stored.get(String(url.url ?? url)),
    }),
    delete: async () => stored.clear(),
  });
  await AppDB.setMeta('principal', '7');
});

/** Post 'cache-page' for /app/ and wait for the worker to finish with it. */
async function cachePage(fetchImpl) {
  vi.stubGlobal('fetch', vi.fn(fetchImpl));
  let work;
  onMessage({ data: { type: 'cache-page', url: '/app/' }, waitUntil: (promise) => (work = promise) });
  await work;
  return [...stored.keys()].some((url) => url.endsWith('/app/'));
}

const page = () => ({ ok: true, redirected: false, type: 'basic', headers: new Headers() });

describe('cache-page', () => {
  it('stores the page for the signed-in user', async () => {
    expect(await cachePage(async () => page())).toBe(true);
  });

  it('takes the copy out again when a sign-out started during the fetch', async () => {
    const cached = await cachePage(async () => {
      await AppDB.setMeta('principal', '');
      return page();
    });
    expect(cached).toBe(false);
  });

  it('takes the copy out when another user signed in during the fetch', async () => {
    const cached = await cachePage(async () => {
      await AppDB.setMeta('principal', '8');
      return page();
    });
    expect(cached).toBe(false);
  });

  it('fetches nothing once signed out', async () => {
    await AppDB.setMeta('principal', '');
    expect(await cachePage(async () => page())).toBe(false);
    expect(fetch).not.toHaveBeenCalled();
  });
});

/** Navigate to /app/ through the worker's fetch handler and wait for it to finish. */
async function visit(response) {
  vi.stubGlobal('fetch', vi.fn(async () => response));
  const work = [];
  let reply;
  const request = { url: `${self.location.origin}/app/`, method: 'GET', mode: 'navigate' };
  onFetch({ request, respondWith: (promise) => (reply = promise), waitUntil: (promise) => work.push(promise) });
  await reply;
  await Promise.all(work);
}

describe('page fetch', () => {
  const cachedUrl = () => `${self.location.origin}/app/`;
  const otherUrl = () => `${self.location.origin}/app/other/`;

  it.each([
    ['sent on to sign-in', { redirected: true }],
    ['refused', { ok: false, status: 403 }],
  ])('forgets every cached page and the principal when a page is %s', async (_, overrides) => {
    stored.set(cachedUrl(), page());
    stored.set(otherUrl(), page());
    await visit({ ...page(), ...overrides });
    expect(stored.size).toBe(0);
    expect(await AppDB.getMeta('principal')).toBe('');
  });

  it('still forgets the pages when a slow sign-out arrives after the cached copy', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout'] });
    try {
      stored.set(cachedUrl(), page());
      let answer;
      vi.stubGlobal('fetch', vi.fn(() => new Promise((resolve) => (answer = resolve))));
      const events = [];
      let reply;
      const request = { url: cachedUrl(), method: 'GET', mode: 'navigate' };
      onFetch({
        request,
        respondWith: (promise) => (reply = promise.then((r) => (events.push('replied'), r))),
        waitUntil: (promise) => (events.push('waitUntil'), (reply.cleanup = promise)),
      });
      await vi.advanceTimersByTimeAsync(4000);
      expect(await reply).toBe(stored.get(cachedUrl()));
      answer({ ...page(), redirected: true });
      await reply.cleanup;
      expect(events).toEqual(['waitUntil', 'replied']);
      expect(stored.size).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps the cached copy through a server error', async () => {
    stored.set(cachedUrl(), page());
    await visit({ ...page(), ok: false, status: 500 });
    expect(stored.has(cachedUrl())).toBe(true);
  });
});

describe('push (RAS-144)', () => {
  async function receive(data) {
    const show = vi.fn(async () => undefined);
    vi.stubGlobal('registration', { showNotification: show });
    let work;
    onPush({ data, waitUntil: (promise) => (work = promise) });
    await work;
    return show;
  }

  it('shows the alert the message carries', async () => {
    const message = { title: 'BA117 has landed', body: 'Landed at JFK.', url: '/app/', tag: 'x-landing' };
    const show = await receive({ json: () => message });
    expect(show).toHaveBeenCalledWith('BA117 has landed', {
      body: 'Landed at JFK.',
      tag: 'x-landing',
      icon: '/static/icons/icon-192.png',
      badge: '/static/icons/icon-192.png',
      data: { url: '/app/' },
    });
  });

  it('still shows something for a message it cannot read', async () => {
    const show = await receive({
      json: () => {
        throw new SyntaxError('not JSON');
      },
    });
    expect(show.mock.calls[0][0]).toBe('Flight');
  });

  it('opens the app on a tap, or focuses it at the page when it is open', async () => {
    const close = vi.fn();
    const focus = vi.fn(async () => undefined);
    const navigate = vi.fn(async () => ({ focus }));
    const openWindow = vi.fn(async () => undefined);
    const tap = async (windows) => {
      vi.stubGlobal('clients', { matchAll: async () => windows, openWindow });
      let work;
      onNotificationClick({ notification: { close, data: { url: '/app/' } }, waitUntil: (p) => (work = p) });
      await work;
    };
    await tap([]);
    expect(openWindow).toHaveBeenCalledWith('/app/');
    await tap([{ url: 'http://localhost/app/account/', navigate, focus }]);
    expect(navigate).toHaveBeenCalledWith('/app/');
    expect(focus).toHaveBeenCalled();
    expect(close).toHaveBeenCalledTimes(2);
  });
});
