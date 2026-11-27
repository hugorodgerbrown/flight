// Tests for apps/mcp/ui/flight_share.js: the card's Share button in Claude's view (RAS-145).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const HTML = readFileSync(resolve(__dirname, '../../../apps/mcp/ui/flight_map.html'), 'utf8');
const LINK = 'https://flight.example/f/abc/';
let onResult;

async function load(callTool) {
  document.body.innerHTML = HTML.slice(HTML.indexOf('<body>') + 6, HTML.indexOf('</body>'));
  self.McpApp = { onToolResult: (listener) => (onResult = listener), callTool };
  vi.resetModules();
  await import('../../../apps/mcp/ui/flight_share.js');
}

const q = (name) => document.querySelector(`[data-share-${name}]`);
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => {
  delete self.McpApp;
  delete self.FlightShareButton;
});

describe('the Share button', () => {
  let callTool;
  beforeEach(async () => {
    callTool = vi.fn();
    await load(callTool);
  });

  it('shows for a flight in the air or landed, not for an error or no position', () => {
    onResult({ structuredContent: { flight: 'BA117', status: 'airborne' } });
    expect(q('box').hidden).toBe(false);
    onResult({ structuredContent: { flight: 'BA117', status: 'lost' } });
    expect(q('box').hidden).toBe(true);
    onResult({ structuredContent: { flight: 'BA117', status: 'landed' } });
    expect(q('box').hidden).toBe(false);
    onResult({ isError: true, content: [{ type: 'text', text: 'No' }] });
    expect(q('box').hidden).toBe(true);
  });

  it('makes the link with share_flight and shows it to copy', async () => {
    callTool.mockResolvedValue({ structuredContent: { url: LINK } });
    onResult({ structuredContent: { flight: 'BA117', status: 'airborne' } });
    q('button').click();
    expect(q('button').textContent).toBe('Making the link…');
    await flush();
    expect(callTool).toHaveBeenCalledWith('share_flight', { flight: 'BA117' });
    expect(q('url').value).toBe(LINK);
    expect(q('link').hidden).toBe(false);
    expect(q('button').hidden).toBe(true);
    expect(q('note').textContent).toContain('without signing in');
  });

  it('says why when the link cannot be made, and lets the user try again', async () => {
    callTool.mockResolvedValue({ isError: true, content: [{ type: 'text', text: 'BA117 is not flying.' }] });
    onResult({ structuredContent: { flight: 'BA117', status: 'airborne' } });
    q('button').click();
    await flush();
    expect(q('note').textContent).toBe('BA117 is not flying.');
    expect(q('button').disabled).toBe(false);
    callTool.mockRejectedValue(new Error('Host refused'));
    q('button').click();
    await flush();
    expect(q('note').textContent).toBe('Host refused');
    callTool.mockResolvedValue({});
    q('button').click();
    await flush();
    expect(q('note').textContent).toBe("The link couldn't be made. Try again in a minute.");
  });

  it('copies the link, or selects it where the clipboard is blocked', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    q('url').value = LINK;
    q('copy').click();
    await flush();
    expect(writeText).toHaveBeenCalledWith(LINK);
    expect(q('copy').textContent).toBe('Copied');
    writeText.mockRejectedValue(new Error('blocked'));
    q('copy').click();
    await flush();
    expect(q('copy').textContent).toBe('Selected');
  });
});

describe('outside Claude', () => {
  it('does nothing without the bridge', async () => {
    document.body.innerHTML = '';
    self.McpApp = { onToolResult: () => {} };
    vi.resetModules();
    await import('../../../apps/mcp/ui/flight_share.js');
    expect(self.FlightShareButton).toBeUndefined();
  });
});
