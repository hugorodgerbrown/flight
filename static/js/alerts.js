/*
 * static/js/alerts.js — turning notifications on for this browser (RAS-144).
 *
 * Finds [data-push] (templates: alerts/_push.html), works out this
 * browser's state and shows the parts marked for it with data-push-when:
 *
 *   off          push works here but isn't on: a Turn on button
 *   on           this browser gets alerts: a Turn off button
 *   blocked      the person said no: where to change it
 *   install      an iPhone or iPad outside the Home Screen app, where Safari has no push
 *   unsupported  no push in this browser
 *
 * data-push-shown-in lists the states the whole block shows in (the home
 * page's banner shows only off and install). Permission is asked only on a
 * tap of Turn on, never on load. The subscription is sent to
 * data-subscribe-url as JSON, with the page's CSRF token.
 */
(function () {
  'use strict';

  /** Return a base64url string as the bytes PushManager.subscribe takes. */
  function keyBytes(text) {
    const padded = text + '='.repeat((4 - (text.length % 4)) % 4);
    const raw = atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }

  function isAppleMobile(nav) {
    return /iPhone|iPad|iPod/.test(nav.userAgent) || (nav.platform === 'MacIntel' && nav.maxTouchPoints > 1);
  }

  function isStandalone(win) {
    return Boolean(
      (win.matchMedia && win.matchMedia('(display-mode: standalone)').matches) || win.navigator.standalone
    );
  }

  /** The state before asking anything of the push service. */
  function baseState(win) {
    const nav = win.navigator;
    const supported = 'serviceWorker' in nav && 'PushManager' in win && 'Notification' in win;
    if (!supported) return isAppleMobile(nav) && !isStandalone(win) ? 'install' : 'unsupported';
    if (win.Notification.permission === 'denied') return 'blocked';
    return 'off';
  }

  function show(root, state) {
    root.dataset.pushState = state;
    const shownIn = (root.dataset.pushShownIn || '').split(/\s+/);
    root.hidden = !shownIn.includes(state);
    root.querySelectorAll('[data-push-when]').forEach((part) => {
      part.hidden = !part.dataset.pushWhen.split(/\s+/).includes(state);
    });
  }

  function csrfToken(doc) {
    const meta = doc.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : '';
  }

  async function post(url, body, doc) {
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken(doc) },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error('alerts: ' + url + ' answered ' + response.status);
    return response;
  }

  function fail(root, text) {
    const error = root.querySelector('[data-push-error]');
    if (!error) return;
    error.textContent = text;
    error.hidden = false;
  }

  async function turnOn(root, win) {
    const permission = await win.Notification.requestPermission();
    if (permission !== 'granted') {
      show(root, permission === 'denied' ? 'blocked' : 'off');
      return;
    }
    const registration = await win.navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes(root.dataset.pushKey),
    });
    await post(root.dataset.subscribeUrl, subscription.toJSON(), win.document);
    show(root, 'on');
  }

  async function turnOff(root, win) {
    const registration = await win.navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.getSubscription();
    if (subscription) {
      await post(root.dataset.unsubscribeUrl, { endpoint: subscription.endpoint }, win.document);
      await subscription.unsubscribe();
    }
    show(root, 'off');
  }

  /** Work out the state, show it, and wire the buttons. Returns the state shown. */
  async function enhance(root, win) {
    let state = baseState(win);
    if (state === 'off') {
      const registration = await win.navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription();
      if (subscription) {
        state = 'on';
        // Tell the server again: the account may have changed, or the row been dropped.
        post(root.dataset.subscribeUrl, subscription.toJSON(), win.document).catch(() => undefined);
      }
    }
    show(root, state);
    const on = root.querySelector('[data-push-on]');
    const off = root.querySelector('[data-push-off]');
    if (on) {
      on.addEventListener('click', () => {
        on.disabled = true;
        turnOn(root, win)
          .catch(() => fail(root, "Notifications couldn't be turned on. Try again."))
          .finally(() => {
            on.disabled = false;
          });
      });
    }
    if (off) {
      off.addEventListener('click', () => {
        off.disabled = true;
        turnOff(root, win)
          .catch(() => fail(root, "Notifications couldn't be turned off. Try again."))
          .finally(() => {
            off.disabled = false;
          });
      });
    }
    return state;
  }

  function start() {
    document.querySelectorAll('[data-push]').forEach((root) => {
      enhance(root, window).catch(() => show(root, 'unsupported'));
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();

  self.Alerts = Object.freeze({ keyBytes, baseState, show, enhance, turnOn, turnOff });
})();
