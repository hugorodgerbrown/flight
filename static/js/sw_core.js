/*
 * static/js/sw_core.js — the service worker's decisions, as pure functions.
 *
 * Which strategy a request gets, what the caches are called, whether a
 * response may be stored, and what a push message shows. Unit-tested in tests/js/test_sw_core.js;
 * sw_worker.js does the caching.
 */
(function () {
  'use strict';

  /** Cache Storage names for this worker version. */
  function cacheNames(config) {
    return {
      static: config.prefix + '-static-' + config.version,
      pages: config.prefix + '-pages-' + config.version,
    };
  }

  /** True for a cache this app owns but this version doesn't use. */
  function isStaleCache(name, config) {
    const current = Object.values(cacheNames(config));
    return name.startsWith(config.prefix + '-') && !current.includes(name);
  }

  /**
   * How to answer a request.
   *   'bypass'  let the browser handle it (writes, other origins, the worker itself,
   *             anything outside the app's scope, never-cache paths)
   *   'static'  cache-first (hashed, immutable file names); network-first in DEBUG
   *   'page'    network-first with a timeout, then the cached copy, then the offline page
   * @param {{method: string}} request
   * @param {URL} url
   */
  function route(request, url, origin, config) {
    if (request.method !== 'GET') return 'bypass';
    if (url.origin !== origin) return 'bypass';
    if (url.pathname === config.workerUrl) return 'bypass';
    if (url.pathname.startsWith(config.staticUrl)) return 'static';
    // Public pages, sign-in, admin, OAuth: a controlled page can still fetch
    // them, but they are never the app's to cache.
    if (!url.pathname.startsWith(config.scope)) return 'bypass';
    if (config.neverCache.some((prefix) => url.pathname.startsWith(prefix))) return 'bypass';
    return 'page';
  }

  /**
   * True when a response can be stored and served later. Signed-in pages are
   * no-store so the browser's own cache never holds them; the server marks the
   * ones this worker may still keep (apps/core/private_pages.py), since
   * pwa.js deletes this cache before signing out.
   */
  function isStorable(response) {
    if (!response || !response.ok || response.redirected || response.type !== 'basic') return false;
    if (response.headers.get('Offline-Copy') === 'allowed') return true;
    const cacheControl = response.headers.get('Cache-Control') || '';
    return !/no-store/i.test(cacheControl);
  }

  /**
   * Whether a page's response says the session that cached it is gone: it
   * was sent on to sign-in, or refused. Its cached copy must go too, or an
   * offline visit would still show the old private page.
   */
  function isSignedOut(response) {
    return response.redirected || response.status === 401 || response.status === 403;
  }

  /**
   * The notification a push message shows (RAS-144): a take-off or landing
   * alert's title and body, tagged so a repeat replaces rather than stacks,
   * and the app page a tap opens. A message that isn't one of ours still
   * shows something, because a push must always show a notification.
   * @param {object|null} data  the push message's JSON
   * @param {object} config  the worker's config (scope, icon)
   */
  function notificationFor(data, config) {
    const message = data && typeof data === 'object' ? data : {};
    const url = typeof message.url === 'string' && message.url.startsWith(config.scope) ? message.url : config.scope;
    return {
      title: typeof message.title === 'string' && message.title ? message.title : config.appName,
      options: {
        body: typeof message.body === 'string' ? message.body : '',
        tag: typeof message.tag === 'string' ? message.tag : undefined,
        icon: config.icon,
        badge: config.icon,
        data: { url: url },
      },
    };
  }

  self.SwCore = Object.freeze({ cacheNames, isStaleCache, route, isStorable, isSignedOut, notificationFor });
})();
