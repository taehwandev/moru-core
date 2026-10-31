#!/usr/bin/env node
// Observe a built web page in a real browser and write evidence, nothing else.
//
// Usage: node observe.mjs <url> <out-dir> [--viewport desktop|mobile] [--seconds N]
//
// Drives Chrome over the DevTools protocol with no dependencies. It loads the
// page, records console errors and failed requests, finds the page's primary
// action by its visible label, activates it as a user would, and captures
// screenshots and visible text over time. It never edits the page and never
// judges; verify.py does that from this evidence.
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [url, outDir, ...rest] = process.argv.slice(2);
if (!url || !outDir) {
  console.error('usage: observe.mjs <url> <out-dir> [--viewport desktop|mobile] [--seconds N]');
  process.exit(2);
}
const option = (name, fallback) => {
  const at = rest.indexOf(name);
  return at >= 0 && rest[at + 1] ? rest[at + 1] : fallback;
};
const viewportName = option('--viewport', 'desktop');
const totalSeconds = Number(option('--seconds', '75'));
const CHROME = process.env.CHROME_PATH
  || ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome',
    '/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
if (!CHROME) {
  console.error('no Chrome found; set CHROME_PATH');
  process.exit(3);
}
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const viewport = viewportName === 'mobile'
  ? { width: 390, height: 844, deviceScaleFactor: 1, mobile: true }
  : { width: 1024, height: 640, deviceScaleFactor: 1, mobile: false };

mkdirSync(outDir, { recursive: true });
const profile = mkdtempSync(join(tmpdir(), 'moru-page-verify-'));
// Few helper processes on purpose: a container's process limit is shared with the agent's own builds.
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run',
  '--no-default-browser-check', '--mute-audio', '--in-process-gpu', '--no-zygote', '--renderer-process-limit=1',
  '--disable-dev-shm-usage', '--disable-extensions', '--disable-sync', '--disable-background-networking',
  '--disable-component-update', '--metrics-recording-only',
  ...(process.env.MORU_VERIFY_CHROME_ARGS || '').split(/\s+/).filter(Boolean), 'about:blank',
], { stdio: 'ignore', detached: true });

// The browser runs in its own process group so that every helper dies with it, whatever happens here.
const killBrowser = () => {
  try { process.kill(-chrome.pid, 'SIGKILL'); } catch { /* already gone */ }
};
process.on('exit', killBrowser);
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => { killBrowser(); process.exit(130); });
setTimeout(() => { killBrowser(); console.error('observer watchdog expired'); process.exit(4); },
  (totalSeconds + 120) * 1000).unref();

async function connect() {
  const portFile = join(profile, 'DevToolsActivePort');
  for (let i = 0; i < 100 && !existsSync(portFile); i += 1) await sleep(100);
  const port = readFileSync(portFile, 'utf8').split('\n')[0];
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = targets.find((target) => target.type === 'page');
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let counter = 0;
  const pending = new Map();
  const listeners = [];
  socket.onmessage = (message) => {
    const data = JSON.parse(message.data);
    if (data.id && pending.has(data.id)) {
      pending.get(data.id)(data);
      pending.delete(data.id);
    } else if (data.method) {
      listeners.forEach((listener) => listener(data));
    }
  };
  const send = (method, params = {}) => new Promise((resolve) => {
    counter += 1;
    pending.set(counter, resolve);
    socket.send(JSON.stringify({ id: counter, method, params }));
  });
  return { send, on: (listener) => listeners.push(listener), close: () => socket.close() };
}

const evidence = {
  url, viewport: viewportName, browser: CHROME, consoleErrors: [], failedRequests: [],
  primaryAction: null, steps: [],
};

async function evaluate(cdp, expression) {
  const result = await cdp.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  return result.result?.result?.value;
}

const FIND_PRIMARY = `(() => {
  const pattern = /(take.?off|launch|start|begin|initiate|play|go\\b|fly|run|deploy)/i;
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 4 && r.height > 4 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const nodes = [...document.querySelectorAll('button, [role=button], a, input[type=button]')].filter(visible);
  const label = (el) => (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
  const hit = nodes.find((el) => pattern.test(label(el)));
  if (!hit) return null;
  const r = hit.getBoundingClientRect();
  return { text: label(hit).slice(0, 60), x: r.left + r.width / 2, y: r.top + r.height / 2 };
})()`;

const FIND_SECONDARY = `(() => {
  const allow = /(orbit|chase|follow|tower|cockpit|drone|cam|view|zoom|pan|^\\s*[+\u2212-]\\s*$)/i;
  const deny = /(reset|land|return|abort|restart|stop|pause|again|reload|clear|exit|close|mute|sound|audio|speed|help|guide|\\?)/i;
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 4 && r.height > 4 && r.bottom > 0 && r.top < innerHeight && s.visibility !== 'hidden' && s.display !== 'none'; };
  const label = (el) => (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').replace(/\\s+/g, ' ').trim();
  const out = [];
  for (const el of document.querySelectorAll('button, [role=button], [role=tab], input[type=button]')) {
    const text = label(el);
    if (!visible(el) || !text || text.length > 24 || deny.test(text) || !allow.test(text)) continue;
    const r = el.getBoundingClientRect();
    out.push({ text, x: r.left + r.width / 2, y: r.top + r.height / 2 });
  }
  return out.slice(0, 8);
})()`;

const SNAPSHOT = `(() => ({
  text: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 1200),
  overflowX: document.documentElement.scrollWidth - innerWidth,
  canvases: [...document.querySelectorAll('canvas')].map((c) => ({ w: c.width, h: c.height })),
}))()`;

let shotIndex = 0;
async function capture(cdp, label, seconds) {
  const shot = await cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: 45 });
  const file = `${String(shotIndex).padStart(2, '0')}-${label}.jpg`;
  shotIndex += 1;
  writeFileSync(join(outDir, file), Buffer.from(shot.result.data, 'base64'));
  evidence.steps.push({ label, seconds, screenshot: file, shotHash: createHash('sha1').update(shot.result.data).digest('hex'),
    ...(await evaluate(cdp, SNAPSHOT)) });
}

try {
  const cdp = await connect();
  cdp.on((event) => {
    if (event.method === 'Runtime.exceptionThrown') {
      const details = event.params.exceptionDetails;
      evidence.consoleErrors.push((details.exception?.description || details.text || 'exception').slice(0, 300));
    } else if (event.method === 'Runtime.consoleAPICalled' && event.params.type === 'error') {
      evidence.consoleErrors.push(event.params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 300));
    } else if (event.method === 'Network.responseReceived' && event.params.response.status >= 400) {
      evidence.failedRequests.push({ url: event.params.response.url, status: event.params.response.status });
    }
  });
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  await cdp.send('Network.enable');
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: viewport.width, height: viewport.height, deviceScaleFactor: viewport.deviceScaleFactor, mobile: viewport.mobile,
  });
  if (viewport.mobile) await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true });
  await cdp.send('Page.navigate', { url });
  await sleep(3500);
  await capture(cdp, 'initial', 0);
  const restKey = (text) => String(text).replace(/[0-9.:%]+/g, '').replace(/\s+/g, ' ').trim();
  const initialKey = restKey(evidence.steps[0].text);

  const primary = await evaluate(cdp, FIND_PRIMARY);
  evidence.primaryAction = primary;
  const press = async (spot) => {
    const pointer = { x: spot.x, y: spot.y, button: 'left', clickCount: 1 };
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', ...pointer });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', ...pointer });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...pointer });
  };
  if (primary) {
    const before = (await evaluate(cdp, SNAPSHOT)).text;
    await press(primary);
    const started = Date.now();
    await sleep(2000);
    // A click can be swallowed while a page is still starting up; try once more before calling it unresponsive.
    evidence.primaryAttempts = 1;
    if ((await evaluate(cdp, SNAPSHOT)).text === before) {
      const again = (await evaluate(cdp, FIND_PRIMARY)) || primary;
      await press(again);
      evidence.primaryAttempts = 2;
      await sleep(1500);
    }
    const at = () => (Date.now() - started) / 1000;
    // The default camera comes first: the subject must be in view before any view is changed.
    for (const mark of [3, 6, 10]) {
      const wait = mark * 1000 - (Date.now() - started);
      if (wait > 0) await sleep(wait);
      await capture(cdp, `default-view-t${mark}s`, mark);
    }
    // Secondary controls (camera, view, zoom) are then exercised once, while the action is still running.
    evidence.secondaryControls = [];
    // At most five distinct controls, and one zoom direction: more screenshots show nothing new.
    const seen = new Set();
    const controls = ((await evaluate(cdp, FIND_SECONDARY)) || []).filter((control) => {
      const key = /^\s*[+\u2212-]\s*$/.test(control.text) ? 'zoom' : control.text;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).slice(0, 5);
    for (const control of controls) {
      await press(control);
      await sleep(900);
      evidence.secondaryControls.push(control.text);
      await capture(cdp, `control-${control.text.replace(/[^a-z0-9]+/gi, '-').toLowerCase().slice(0, 14)}`, at());
    }
    // Then the rest of the timeline in whatever view is active, ending as soon as the page is back at
    // rest (its text matches the initial text apart from numbers) instead of waiting out a fixed window.
    for (const mark of [14, 20, 28, 38, 50, 62, totalSeconds].filter((s) => s <= totalSeconds)) {
      const wait = mark * 1000 - (Date.now() - started);
      if (wait > 0) await sleep(wait);
      await capture(cdp, `late-t${mark}s`, mark);
      if (restKey(evidence.steps[evidence.steps.length - 1].text) === initialKey) {
        evidence.endedAtRest = true;
        break;
      }
    }
  }
  cdp.close();
} catch (error) {
  evidence.observerError = String(error && error.message || error);
} finally {
  evidence.consoleErrors = [...new Set(evidence.consoleErrors)].slice(0, 20);
  writeFileSync(join(outDir, 'observations.json'), JSON.stringify(evidence, null, 2));
  killBrowser();
}
console.log(JSON.stringify({ out: outDir, steps: evidence.steps.length, errors: evidence.consoleErrors.length,
  primary: evidence.primaryAction?.text || null, observerError: evidence.observerError || null }));
