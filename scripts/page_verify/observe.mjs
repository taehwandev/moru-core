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
const totalSeconds = Number(option('--seconds', '40'));
const CHROME = process.env.CHROME_PATH
  || ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome',
    '/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
if (!CHROME) {
  console.error('no Chrome found; set CHROME_PATH');
  process.exit(3);
}
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const viewport = viewportName === 'mobile'
  ? { width: 390, height: 844, deviceScaleFactor: 2, mobile: true }
  : { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false };

mkdirSync(outDir, { recursive: true });
const profile = mkdtempSync(join(tmpdir(), 'moru-page-verify-'));
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run',
  '--no-default-browser-check', '--mute-audio',
  ...(process.env.MORU_VERIFY_CHROME_ARGS || '').split(/\s+/).filter(Boolean), 'about:blank',
], { stdio: 'ignore' });

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
  const allow = /(orbit|chase|follow|tower|cockpit|cam|view|zoom|pan|\\+|\u2212|-|in\\b|out\\b)/i;
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
  const shot = await cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: 60 });
  const file = `${String(shotIndex).padStart(2, '0')}-${label}.jpg`;
  shotIndex += 1;
  writeFileSync(join(outDir, file), Buffer.from(shot.result.data, 'base64'));
  evidence.steps.push({ label, seconds, screenshot: file, ...(await evaluate(cdp, SNAPSHOT)) });
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

  const primary = await evaluate(cdp, FIND_PRIMARY);
  evidence.primaryAction = primary;
  if (primary) {
    const pointer = { x: primary.x, y: primary.y, button: 'left', clickCount: 1 };
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', ...pointer });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', ...pointer });
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...pointer });
    const started = Date.now();
    // Secondary controls (camera, view, zoom) are exercised once, while the action is running,
    // so the evidence shows each camera mode with the subject in motion.
    await sleep(2500);
    evidence.secondaryControls = [];
    for (const control of (await evaluate(cdp, FIND_SECONDARY)) || []) {
      const spot = { x: control.x, y: control.y, button: 'left', clickCount: 1 };
      await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', ...spot });
      await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', ...spot });
      await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...spot });
      await sleep(900);
      evidence.secondaryControls.push(control.text);
      await capture(cdp, `control-${control.text.replace(/[^a-z0-9]+/gi, '-').toLowerCase().slice(0, 14)}`, (Date.now() - started) / 1000);
    }
    // Put the view back to the first mode so the timeline shows the default camera, not the last one tried.
    const first = ((await evaluate(cdp, FIND_SECONDARY)) || []).find((c) => c.text === evidence.secondaryControls[0]);
    if (first) {
      const home = { x: first.x, y: first.y, button: 'left', clickCount: 1 };
      await cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', ...home });
      await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', ...home });
      await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...home });
      await sleep(600);
    }
    const marks = [2, 6, 12, 20, 30, totalSeconds].filter((s) => s <= totalSeconds);
    for (const mark of [...new Set(marks)]) {
      const wait = mark * 1000 - (Date.now() - started);
      if (wait > 0) await sleep(wait);
      await capture(cdp, `t${mark}s`, mark);
    }
  }
  cdp.close();
} catch (error) {
  evidence.observerError = String(error && error.message || error);
} finally {
  evidence.consoleErrors = [...new Set(evidence.consoleErrors)].slice(0, 20);
  writeFileSync(join(outDir, 'observations.json'), JSON.stringify(evidence, null, 2));
  chrome.kill();
}
console.log(JSON.stringify({ out: outDir, steps: evidence.steps.length, errors: evidence.consoleErrors.length,
  primary: evidence.primaryAction?.text || null, observerError: evidence.observerError || null }));
