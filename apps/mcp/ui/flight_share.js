/*
 * apps/mcp/ui/flight_share.js — the map card's Share button, in Claude's view only (RAS-145).
 *
 * For a flight in the air or landed, the card offers "Share a live link". A
 * tap asks the server for one with the share_flight tool, over the bridge,
 * as the signed-in user, and shows the link to copy. The share page itself
 * draws the card without this file.
 */
(function () {
  'use strict';

  if (!self.McpApp || !self.McpApp.callTool) return;
  const q = (name) => document.querySelector(`[data-share-${name}]`);
  const box = q('box');
  const button = q('button');
  const row = q('link');
  const field = q('url');
  const copy = q('copy');
  const note = q('note');
  const LABEL = 'Share a live link';
  let number = null;

  self.McpApp.onToolResult((result) => {
    const flight = result.structuredContent;
    number = flight && flight.flight;
    box.hidden = Boolean(result.isError || !flight || !['airborne', 'landed'].includes(flight.status));
  });

  function fail(text) {
    note.textContent = text || "The link couldn't be made. Try again in a minute.";
    note.hidden = false;
    button.disabled = false;
    button.textContent = LABEL;
  }

  button.addEventListener('click', async () => {
    button.disabled = true;
    button.textContent = 'Making the link…';
    note.hidden = true;
    try {
      const result = await self.McpApp.callTool('share_flight', { flight: number });
      const url = result && !result.isError && result.structuredContent && result.structuredContent.url;
      if (!url) return fail(((result && result.content) || [])[0] && result.content[0].text);
      field.value = url;
      row.hidden = false;
      button.hidden = true;
      note.textContent = 'Anyone with it can follow the flight, without signing in, until a day after it lands.';
      note.hidden = false;
    } catch (error) {
      fail(error && error.message);
    }
  });

  copy.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(field.value);
      copy.textContent = 'Copied';
    } catch {
      // The host's frame may not allow the clipboard: select it to copy by hand.
      field.focus();
      field.select();
      copy.textContent = 'Selected';
    }
  });

  self.FlightShareButton = { fail };
})();
