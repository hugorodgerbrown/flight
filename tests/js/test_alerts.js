// Tests for static/js/alerts.js: turning notifications on for this browser (RAS-144).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../static/js/alerts.js';

const { Alerts } = self;

function block(shownIn = 'off on blocked install unsupported') {
  document.body.innerHTML = `
    <meta name="csrf-token" content="token-1">
    <div data-push data-push-key="AQID" data-subscribe-url="/app/alerts/push/"
         data-unsubscribe-url="/app/alerts/push/delete/" data-push-shown-in="${shownIn}" hidden>
      <p data-push-when="off">off</p><p data-push-when="on">on</p>
      <p data-push-when="blocked">blocked</p><p data-push-when="install">install</p>
      <p data-push-when="unsupported">unsupported</p>
      <button data-push-on data-push-when="off">Turn on</button>
      <button data-push-off data-push-when="on">Turn off</button>
      <p data-push-error hidden></p>
    </div>`;
  return document.querySelector('[data-push]');
}

/** A window with push, a permission, and a subscription (or none). */
function fakeWindow({ permission = 'default', existing = null, asked = 'granted', agent = 'Chrome' } = {}) {
  const subscription = {
    endpoint: 'https://push.example.test/1',
    toJSON: () => ({ endpoint: 'https://push.example.test/1', keys: { p256dh: 'k', auth: 'a' } }),
    unsubscribe: vi.fn(async () => true),
  };
  let current = existing ? subscription : null;
  const pushManager = {
    getSubscription: vi.fn(async () => current),
    subscribe: vi.fn(async () => (current = subscription)),
  };
  return {
    document,
    navigator: { userAgent: agent, serviceWorker: { ready: Promise.resolve({ pushManager }) } },
    PushManager: function () {},
    Notification: { permission, requestPermission: vi.fn(async () => asked) },
    matchMedia: () => ({ matches: false }),
    pushManager,
    subscription,
  };
}

let fetchMock;
beforeEach(() => {
  fetchMock = vi.fn(async () => ({ ok: true, status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

const visible = (root) => [...root.querySelectorAll('[data-push-when]')].filter((p) => !p.hidden).map((p) => p.textContent);

describe('the state shown', () => {
  it('offers Turn on, and asks nothing until it is tapped', async () => {
    const root = block();
    const win = fakeWindow();
    expect(await Alerts.enhance(root, win)).toBe('off');
    expect(root.hidden).toBe(false);
    expect(visible(root)).toEqual(['off', 'Turn on']);
    expect(win.Notification.requestPermission).not.toHaveBeenCalled();
  });

  it('shows on for a subscribed browser, and tells the server again', async () => {
    const root = block();
    expect(await Alerts.enhance(root, fakeWindow({ permission: 'granted', existing: true }))).toBe('on');
    expect(visible(root)).toEqual(['on', 'Turn off']);
    expect(fetchMock).toHaveBeenCalledWith('/app/alerts/push/', expect.objectContaining({ method: 'POST' }));
  });

  it('says notifications are blocked', async () => {
    expect(await Alerts.enhance(block(), fakeWindow({ permission: 'denied' }))).toBe('blocked');
  });

  it('asks an iPhone outside the Home Screen to install, and hides the home banner elsewhere', async () => {
    const iphone = { document, navigator: { userAgent: 'iPhone', platform: 'iPhone' }, matchMedia: () => ({ matches: false }) };
    expect(Alerts.baseState(iphone)).toBe('install');
    const desktop = { document, navigator: { userAgent: 'Firefox', platform: 'Linux' }, matchMedia: () => ({ matches: false }) };
    expect(Alerts.baseState(desktop)).toBe('unsupported');
    const root = block('off install');
    Alerts.show(root, 'unsupported');
    expect(root.hidden).toBe(true);
    Alerts.show(root, 'install');
    expect(root.hidden).toBe(false);
  });
});

describe('turning notifications on and off', () => {
  it('subscribes with the key and sends the subscription with the CSRF token', async () => {
    const root = block();
    const win = fakeWindow();
    await Alerts.turnOn(root, win);
    expect(win.pushManager.subscribe).toHaveBeenCalledWith({
      userVisibleOnly: true,
      applicationServerKey: Uint8Array.from([1, 2, 3]),
    });
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('/app/alerts/push/');
    expect(options.headers['X-CSRFToken']).toBe('token-1');
    expect(JSON.parse(options.body).endpoint).toBe('https://push.example.test/1');
    expect(root.dataset.pushState).toBe('on');
  });

  it('stays off, or shows blocked, when the person says no', async () => {
    const root = block();
    await Alerts.turnOn(root, fakeWindow({ asked: 'default' }));
    expect(root.dataset.pushState).toBe('off');
    await Alerts.turnOn(root, fakeWindow({ asked: 'denied' }));
    expect(root.dataset.pushState).toBe('blocked');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('tells the server, then unsubscribes', async () => {
    const root = block();
    const win = fakeWindow({ permission: 'granted', existing: true });
    await Alerts.turnOff(root, win);
    expect(fetchMock.mock.calls[0][0]).toBe('/app/alerts/push/delete/');
    expect(win.subscription.unsubscribe).toHaveBeenCalled();
    expect(root.dataset.pushState).toBe('off');
  });

  it('says so when the server refuses, from the button', async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 500 });
    const root = block();
    await Alerts.enhance(root, fakeWindow());
    root.querySelector('[data-push-on]').click();
    await vi.waitFor(() => expect(root.querySelector('[data-push-error]').hidden).toBe(false));
    expect(root.querySelector('[data-push-error]').textContent).toContain("couldn't be turned on");
  });

  it('turns off from the button', async () => {
    const root = block();
    const win = fakeWindow({ permission: 'granted', existing: true });
    await Alerts.enhance(root, win);
    root.querySelector('[data-push-off]').click();
    await vi.waitFor(() => expect(root.dataset.pushState).toBe('off'));
  });
});
