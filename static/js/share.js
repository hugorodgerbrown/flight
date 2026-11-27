/*
 * static/js/share.js — keep a share link's card live (RAS-145).
 *
 * The share page draws the same card as Claude's map view, with the same
 * script (flight_map.js). That script takes its flight from McpApp, the MCP
 * view's bridge, so this file stands in for the bridge: it hands over the
 * flight the page loaded with, then asks /f/<token>/live.json again every
 * 30 seconds while the page is open, visible and the flight still in the
 * air. Everything the server sends goes in as text (flight_map.js).
 *
 * Load it before flight_map.js; both are deferred, so they run in order.
 */
(function () {
  'use strict';

  const card = document.querySelector('[data-share]');
  if (!card) return;
  const live = document.querySelector('[data-share-live]');
  const pill = document.querySelector('[data-pill]');
  const every = (Number(card.dataset.pollSeconds) || 30) * 1000;
  const PILL = { live: 'status--airborne', landed: 'status--landed', ended: 'status--ended' };
  const listeners = [];
  let latest = null;
  let timer = null;
  let heardAt = null;

  // The part of the MCP bridge flight_map.js uses.
  self.McpApp = {
    onToolResult(listener) {
      listeners.push(listener);
      if (latest) listener(latest);
    },
  };

  function ago(ms) {
    const seconds = Math.max(0, Math.round(ms / 1000));
    if (seconds < 10) return 'just now';
    if (seconds < 60) return `${seconds} seconds ago`;
    const minutes = Math.round(seconds / 60);
    return minutes === 1 ? 'a minute ago' : `${minutes} minutes ago`;
  }

  // The line over the card: live with when Flightradar24 last heard from the plane, or done.
  function say() {
    const state = card.dataset.state;
    live.classList.toggle('share-live--on', state === 'live');
    if (state === 'live') live.textContent = heardAt ? `Live · updated ${ago(Date.now() - heardAt)}` : 'Live';
    else live.textContent = state === 'landed' ? 'Landed' : 'This link has ended';
  }

  // An ended link keeps the route, but no longer says where the plane is or when it lands.
  function ended(flight) {
    pill.textContent = 'Ended';
    document.querySelector('[data-summary]').textContent = `This link to ${flight.flight} has ended.`;
    document.querySelector('[data-arrives]').textContent = '';
    for (const node of document.querySelectorAll('.flight-map__plane, .flight-map__halo')) node.remove();
  }

  function apply(data) {
    if (!data || !data.flight || !data.flight.origin || !data.flight.destination) return;
    const state = PILL[data.state] ? data.state : 'live';
    card.dataset.state = state;
    const heard = Date.parse(data.flight.seen || data.checked || '');
    heardAt = Number.isFinite(heard) ? heard : null;
    latest = { structuredContent: data.flight };
    for (const listener of listeners) listener(latest);
    pill.classList.remove(...Object.values(PILL));
    pill.classList.add(PILL[state]);
    if (state === 'ended') ended(data.flight);
    say();
  }

  function schedule() {
    if (timer || document.hidden || card.dataset.state !== 'live') return;
    timer = setTimeout(poll, every);
  }

  async function poll() {
    timer = null;
    if (document.hidden || card.dataset.state !== 'live') return;
    try {
      const response = await fetch(card.dataset.feedUrl, { headers: { Accept: 'application/json' } });
      if (response.ok) apply(await response.json());
      // Gone: the link ended and was deleted, or was stopped.
      else if (response.status === 404 && latest) apply({ state: 'ended', flight: latest.structuredContent });
    } catch {
      // Offline or the server didn't answer: the card stays as it was, and the next poll tries again.
    }
    schedule();
  }

  // A tab coming back to the front catches up at once.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden || card.dataset.state !== 'live') return;
    clearTimeout(timer);
    timer = null;
    poll();
  });

  // After flight_map.js has run (deferred scripts run before this event).
  document.addEventListener('DOMContentLoaded', () => {
    try {
      apply(JSON.parse(card.dataset.feed || 'null'));
    } catch {
      // A page without its flight shows the words it was served with.
    }
    schedule();
    setInterval(say, 5000);
  });

  self.FlightShare = { ago, apply, poll };
})();
