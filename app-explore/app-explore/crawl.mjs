// Read-only breadth-first crawl of a web app for app-explore, run from an omp JavaScript eval cell.
//   const { tab } = await ax.openApp(browser, { url, dataDir, mode: 'readonly' });   // guard installed before the first load
//   const counts = await ax.crawl(tab, { dataDir, mediaDir, start: url, mode: 'readonly' });
//   const { tab } = await ax.openGuarded(browser, { url, dataDir, mode, name });      // any other tab (walks): same guard, no login handling
// Every function takes the tab (or the eval `browser`) as an argument: module code cannot see eval prelude globals.
import { access, appendFile, copyFile, mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { inflateSync } from 'node:zlib';
import { basename, join } from 'node:path';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const SAFE = new Set(['GET', 'HEAD', 'OPTIONS']);

// ---------------------------------------------------------------- deny-list

export const DENY_ALWAYS = /(log ?out|sign ?out|abmelden)/i;
// A denied word starts at a word start (so `Absender`, `Display` pass) and, except the stems archiv, veröffentlich,
// bezahl (German compounds: Archivieren, Veröffentlichen, Bezahlen), ends at a word end (so `Saved items` passes).
// A lone `Cancel` dismisses a dialog and stays allowed; `Cancel order` is denied.
export const DENY_READONLY = /(?<![\p{L}\p{N}])(?:(?:delete|remove|send|submit|save|publish|pay|buy|invite|reset|revoke|disconnect|check ?out|löschen|entfernen|senden|absenden|speichern|kaufen|einladen|trennen|stornieren|bestellen)(?![\p{L}\p{N}])|cancel(?=\s+\p{L})|archiv|veröffentlich|bezahl)/iu;

/** True when a control with this accessible name (or link href) must not be pressed in `mode`. */
export function denied(label, mode = 'readonly', href = '') {
  const s = `${label || ''} ${href || ''}`;
  return DENY_ALWAYS.test(s) || (mode === 'readonly' && DENY_READONLY.test(label || ''));
}

// ---------------------------------------------------------------- write guard
//
// readonly means "the crawler's own actions never write", not "the page cannot POST": apps fire POSTs on load
// (tRPC queries, workspace bootstrap, analytics) and break without them. The guard tells the two apart by an
// acting window: act(tab) stamps window.__apxActing before every crawler click or key press; a request within
// ACT_MS of that stamp in the same document is acting. A navigation starts a new document, so its load is passive.
//   passive: POST passes (logged as `passive`); PUT/PATCH/DELETE are rejected.
//   acting:  every write is rejected except POSTs matching `allowPost`, GraphQL bodies without `mutation`, and
//            tRPC calls whose procedures all start with a read verb (logged as `allow`, `graphql`, `trpc`).

const BLOCK_KEY = '__appExploreBlocked';
const PASS_KEY = '__appExplorePassed';
const ACT_MS = 2000;
// A read procedure name starts with one of these lowercase verbs followed by a camelCase capital, `_`, a digit or its
// end: `getUser`, `list`, `is_admin` read; `issueRefund`, `checkout`, `cancel` do not.
export const READ_VERB = /^(get|list|find|search|fetch|count|query|read|resolve|check|has|is|can)(?=[A-Z_\d]|$)/;

function guardSource(allowPost) {
  // Runs in the page before any app script (tab.addInitScript). Plain ES2017, no imports.
  return `(() => {
  if (window.__appExploreGuard) return;
  window.__appExploreGuard = true;
  const allow = ${JSON.stringify(allowPost)}.map((s) => new RegExp(s));
  const READ = ${READ_VERB.toString()};
  const log = (key) => {
    let saved = [];
    try { saved = JSON.parse(sessionStorage.getItem(key) || '[]'); } catch (e) {}
    window[key] = saved;
    return (row) => {
      window[key].push(Object.assign({ page: location.href, ts: Date.now() }, row));
      try { sessionStorage.setItem(key, JSON.stringify(window[key])); } catch (e) {}
    };
  };
  const block = log(${JSON.stringify(BLOCK_KEY)});
  const pass = log(${JSON.stringify(PASS_KEY)});
  const graphqlQuery = (body) => {
    if (typeof body !== 'string') return false;
    let j; try { j = JSON.parse(body); } catch (e) { return false; }
    const list = Array.isArray(j) ? j : [j];
    return list.length > 0 && list.every((x) => x && typeof x.query === 'string' && !/\\bmutation\\b/.test(x.query));
  };
  const trpcQuery = (u) => {
    const m = /\\/trpc\\/([^/?#]+)/.exec(u.pathname);
    if (!m) return false;
    return decodeURIComponent(m[1]).split(',').every((p) => READ.test(p.split('.').pop()));
  };
  const acting = () => typeof window.__apxActing === 'number' && Date.now() - window.__apxActing < ${ACT_MS};
  const allowed = (method, url, body) => {
    method = String(method || 'GET').toUpperCase();
    if (method === 'GET' || method === 'HEAD' || method === 'OPTIONS') return true;
    const u = new URL(String(url), location.href);
    const isActing = acting();
    if (method === 'POST') {
      const why = !isActing ? 'passive'
        : allow.some((r) => r.test(u.href)) ? 'allow'
        : graphqlQuery(body) ? 'graphql'
        : trpcQuery(u) ? 'trpc' : null;
      if (why) { pass({ method, url: u.href, why }); return true; }
    }
    block({ method, url: u.href, acting: isActing });
    return false;
  };
  function SAFE(m) { m = String(m || 'GET').toUpperCase(); return m === 'GET' || m === 'HEAD' || m === 'OPTIONS'; }
  const realFetch = window.fetch;
  window.fetch = async function (input, init) {
    const isReq = typeof Request !== 'undefined' && input instanceof Request;
    const method = (init && init.method) || (isReq ? input.method : 'GET');
    const url = isReq ? input.url : input;
    let body = init && init.body;
    if (body === undefined && isReq && !SAFE(method)) { try { body = await input.clone().text(); } catch (e) {} }
    if (!allowed(method, url, body)) throw new TypeError('app-explore: blocked ' + String(method).toUpperCase());
    return realFetch.apply(this, arguments);
  };
  const open = XMLHttpRequest.prototype.open;
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    this.__ax = { method, url };
    return open.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function (body) {
    const m = this.__ax || {};
    if (!allowed(m.method, m.url, body)) { this.abort(); return; }
    return send.apply(this, arguments);
  };
  if (navigator.sendBeacon) {
    const beacon = navigator.sendBeacon.bind(navigator);
    navigator.sendBeacon = (url, data) => (allowed('POST', url, data) ? beacon(url, data) : false);
  }
  const formOk = (form, submitter) => {
    const method = (submitter && submitter.getAttribute('formmethod')) || form.getAttribute('method') || 'GET';
    const action = (submitter && submitter.getAttribute('formaction')) || form.action || location.href;
    return String(method).toUpperCase() === 'GET' || allowed(method, action, undefined);
  };
  document.addEventListener('submit', (e) => {
    if (!formOk(e.target, e.submitter)) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
  const submit = HTMLFormElement.prototype.submit;
  HTMLFormElement.prototype.submit = function () { if (formOk(this)) return submit.apply(this, arguments); };
})();`;
}

/** Open the acting window: call right before every click or key press the crawler (or a walker) performs. */
export async function act(tab) {
  try { await tab.evaluate('window.__apxActing = Date.now()'); } catch {}
}

/**
 * Install the write guard (rules above), replacing a guard installed earlier on this tab (to change `allowPost`).
 * sandbox: no request guard (the click deny-list still keeps logout away). Reloads an already loaded page so the
 * guard is in place before the app's own scripts; on about:blank (openApp) there is nothing to reload.
 */
export async function readOnly(tab, { mode = 'readonly', dataDir, allowPost = [] } = {}) {
  if (dataDir) {
    await mkdir(dataDir, { recursive: true });
    for (const f of ['blocked.jsonl', 'passive.jsonl', 'leaks.jsonl']) await appendFile(join(dataDir, f), '');
  }
  for (const s of await tab.initScripts()) if (String(s.source).includes('__appExploreGuard')) await tab.removeInitScript(s.id);
  if (mode !== 'readonly') return { mode, guard: false };
  await tab.addInitScript(guardSource(allowPost));
  await tab.setDialogs('dismiss'); // "Really delete?" confirms answer no
  const url = await tab.url();
  if (url && !url.startsWith('about:')) { await tab.reload(); await quiet(tab, { render: RENDER_MS }); }
  return { mode, guard: true };
}

async function drainKey(tab, key) {
  try {
    return await tab.evaluate(`(() => {
      const out = (window[${JSON.stringify(key)}] || []).splice(0);
      try { sessionStorage.removeItem(${JSON.stringify(key)}); } catch (e) {}
      return out;
    })()`) || [];
  } catch { return []; }
}

/**
 * Move the page's guard logs to <data>/blocked.jsonl (rejected writes) and <data>/passive.jsonl (writes the guard let
 * through, `why`: passive|allow|graphql|trpc). Each row's `state` is the id of the state whose page produced it (null
 * when unknown, e.g. in a walk), `task` the walk's task id (null in the crawl), `page` the URL the write was made on.
 * The guard's own test request (guardCheck) lands in blocked.jsonl with `why: "selfcheck"` and is not counted.
 * Returns how many blocked entries were moved.
 */
export async function drainBlocked(tab, dataDir, { state = null, task = null } = {}) {
  const blocked = await drainKey(tab, BLOCK_KEY);
  const passed = await drainKey(tab, PASS_KEY);
  const row = (r, extra) => JSON.stringify({ method: r.method, url: r.url, ...extra, state, task, page: r.page, ts: r.ts }) + '\n';
  const self = (r) => String(r.url).includes(SELFCHECK);
  await appendFile(join(dataDir, 'blocked.jsonl'), blocked.map((r) => row(r, { acting: r.acting, ...(self(r) ? { why: 'selfcheck' } : {}) })).join(''));
  await appendFile(join(dataDir, 'passive.jsonl'), passed.map((r) => row(r, { why: r.why })).join(''));
  return blocked.filter((r) => !self(r)).length;
}

const SELFCHECK = '__apx_selfcheck';

/**
 * Prove the guard works: a DELETE from the page must come back rejected. Returns the page's answer, in readonly mode
 * `app-explore: blocked DELETE`; in sandbox mode it sends nothing and returns null (there the DELETE would go through).
 * Its blocked.jsonl row carries `why: "selfcheck"`; crawl counts skip it.
 */
export async function guardCheck(tab, dataDir, mode = 'readonly') {
  if (mode !== 'readonly') return null;
  const answer = await tab.evaluate(`fetch('/?${SELFCHECK}=1', { method: 'DELETE' }).then(() => 'sent', (e) => e.message)`);
  await drainBlocked(tab, dataDir);
  return answer;
}

// Per data dir: passive.jsonl line indexes already matched to a request, and requests already judged. Request seqs
// count per tab from 1 (a reopened tab starts over), so a request is keyed by tab name, seq and start time.
const audit = new Map();

/**
 * Append every write that reached the server since `sinceSeq` and that the guard did not let through on purpose to
 * <data>/leaks.jsonl. A write request (non-GET/HEAD/OPTIONS with a response status) is excused by an unused
 * passive.jsonl entry with the same method and URL (fragment ignored) and pass.ts - 1 s <= request.ts <= pass.ts + 10 s;
 * each entry excuses one request. Requests still waiting for a response hold back the returned seq so the next call
 * checks them again. Leak rows carry `state`, `task` (as drainBlocked) and `page`, the tab's URL at audit time.
 * Returns the seq to pass as the next `sinceSeq` for this tab.
 */
export async function auditLeaks(tab, dataDir, sinceSeq = 0, { state = null, task = null } = {}) {
  await drainBlocked(tab, dataDir, { state, task });
  if (!audit.has(dataDir)) audit.set(dataDir, { used: new Set(), judged: new Set() });
  const { used, judged } = audit.get(dataDir);
  let passes = [];
  try { passes = (await readFile(join(dataDir, 'passive.jsonl'), 'utf8')).split('\n').filter(Boolean).map((l) => JSON.parse(l)); } catch {}
  const bare = (u) => { try { const x = new URL(u); x.hash = ''; return x.href; } catch { return u; } };
  const reqs = await tab.requests();
  let page = null;
  try { page = await tab.url(); } catch {}
  let seq = sinceSeq, pending = false;
  const lines = [];
  for (const r of reqs) {
    const s = r.seq ?? 0;
    if (s <= sinceSeq) continue;
    const write = !SAFE.has(String(r.method).toUpperCase());
    if (write && r.status == null && !r.failureText) pending = true;
    if (!pending) seq = Math.max(seq, s);
    const key = `${tab.name}|${s}|${r.ts}`;
    if (!write || r.status == null || judged.has(key)) continue;
    judged.add(key);
    const i = passes.findIndex((p, k) => !used.has(k) && p.method === String(r.method).toUpperCase()
      && bare(p.url) === bare(r.url) && r.ts >= p.ts - 1000 && r.ts <= p.ts + 10_000);
    if (i >= 0) { used.add(i); continue; }
    lines.push(JSON.stringify({ seq: s, method: r.method, url: r.url, status: r.status, state, task, page }) + '\n');
  }
  await appendFile(join(dataDir, 'leaks.jsonl'), lines.join(''));
  return seq;
}

// ---------------------------------------------------------------- page helpers

async function lastSeq(tab) {
  const r = await tab.requests();
  return r.length ? (r[r.length - 1].seq ?? r.length) : 0;
}

// Requests still waiting for an answer (streams and long polls older than 30 s excluded: they never finish).
async function inflight(tab) {
  const r = await tab.requests();
  const now = Date.now();
  return r.filter((x) => x.status == null && !x.failureText && !/eventsource|websocket/i.test(x.resourceType || '')
    && now - (x.ts || now) < 30_000).length;
}

// Longest wait for a page load to settle. An unbundled Vite dev server loads ~1500 modules per full page load and
// can render a minute after the first request; the wait ends once the page has held still for RENDER_IDLE_MS. A page
// with fewer than SPARSE controls must hold still for SPARSE_IDLE_MS: a booting SPA can show a lone banner or a
// "taking too long" screen with one Reload button for 20 s before its shell appears.
const RENDER_MS = 120_000;
const RENDER_IDLE_MS = 2000;
const SPARSE = 3;
const SPARSE_IDLE_MS = 30_000;

/**
 * Wait for <body>, then until no new request has started for 500 ms (cap 5 s). With `render` (ms), then also wait
 * until no request is in flight and the URL, the number of visible interactive elements and the number of loaded
 * scripts and styles have held still for RENDER_IDLE_MS (SPARSE_IDLE_MS while fewer than SPARSE controls show):
 * a cold SPA can redirect and render long after the network first goes quiet, and a global banner can show buttons
 * before the app shell exists. Finished fetches are left out so a polling page still settles. Gives up after
 * `render` ms; then lets it settle once more. Returns whether an interactive element showed up (always true without
 * `render`).
 */
export async function quiet(tab, { idle = 500, cap = 5000, render = 0 } = {}) {
  try { await tab.waitForSelector('body', { timeout: cap }); } catch {}
  const t0 = Date.now();
  let seq = await lastSeq(tab);
  let since = Date.now();
  while (Date.now() - t0 < cap) {
    await sleep(100);
    const s = await lastSeq(tab);
    if (s !== seq) { seq = s; since = Date.now(); } else if (Date.now() - since >= idle) break;
  }
  if (!render) return true;
  const t1 = Date.now();
  let last = null, shown = 0, waited = false;
  since = Date.now();
  while (Date.now() - t1 < render) {
    let loaded = 0;
    try {
      [shown, loaded] = await tab.evaluate(`[[...document.querySelectorAll(${JSON.stringify(INTERACTIVE)})].filter((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; }).length,
        performance.getEntriesByType('resource').filter((r) => !['fetch', 'xmlhttprequest', 'beacon'].includes(r.initiatorType)).length]`);
    } catch { shown = 0; }
    const busy = await inflight(tab);
    const now = `${await tab.url()}|${shown}|${loaded}`;
    if (now !== last || busy) { last = now; since = Date.now(); }
    else if (Date.now() - since >= (shown < SPARSE ? SPARSE_IDLE_MS : RENDER_IDLE_MS)) break;
    waited = true;
    await sleep(250);
  }
  if (waited) await quiet(tab, { idle, cap });
  return shown > 0;
}

/** URL path with numeric, UUID and long hex/base62 segments replaced by `:id` (hash routes included). */
export function routeOf(href) {
  const u = new URL(href);
  const hashRoute = /^#[!/]/.test(u.hash) ? u.hash.replace(/^#!?/, '').split('?')[0] : '';
  const norm = (p) => p.split('/').map((seg) => (
    /^\d+$/.test(seg)
    || /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(seg)
    || (/^[A-Za-z0-9_-]{16,}$/.test(seg) && /\d/.test(seg))
      ? ':id' : seg)).join('/');
  return norm(u.pathname) + (hashRoute ? `#${norm(hashRoute)}` : '');
}

/** URL without fragment, except hash-router fragments (`#/…`, `#!…`). */
export function normUrl(href) {
  const u = new URL(href);
  if (!/^#[!/]/.test(u.hash)) u.hash = '';
  return u.href;
}

const LOGIN_PATH = /login|signin|sign-in|auth/i;

/** True on a login wall: the URL path names a login, or a visible password field exists. */
export async function isLogin(tab) {
  const url = await tab.url();
  let path = '';
  try { const u = new URL(url); path = u.pathname + u.hash; } catch {}
  if (LOGIN_PATH.test(path)) return true;
  try {
    return await tab.evaluate(`[...document.querySelectorAll('input[type=password]')].some((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; })`);
  } catch { return false; }
}

const VIEWPORT = { width: 1280, height: 800 };
const MANAGED = { relay: false, tern: false };

async function settle(tab, url) {
  try { await tab.goto(url); } catch {}
  await quiet(tab, { render: RENDER_MS });
}

/**
 * Open `url` in a hidden managed tab named `name` with the write guard in place before the app's first request: the
 * tab starts on about:blank, readOnly() installs the guard (rules above), <data>/auth.json is loaded when present,
 * then the URL loads and renders. Returns {tab, saved} (`saved`: auth.json was loaded). Every app tab of a run (the
 * crawl through openApp, each walk) opens through here.
 */
export async function openGuarded(browser, { url, dataDir, mode = 'readonly', allowPost = [], name = 'explore', viewport = VIEWPORT, headed = false } = {}) {
  await mkdir(dataDir, { recursive: true });
  const tab = await browser.open({ name, url: 'about:blank', app: MANAGED, viewport, persist: true, ...(headed ? { headed } : {}) });
  await readOnly(tab, { mode, dataDir, allowPost });
  const authPath = join(dataDir, 'auth.json');
  const saved = await access(authPath).then(() => true, () => false);
  if (saved) await tab.loadState(authPath);
  await settle(tab, url);
  return { tab, saved };
}

/**
 * openGuarded() for the crawl, plus the login: on a login wall, export the session from the user's Chrome (relay
 * tab → <data>/auth.json → loadState). Returns {tab, lang, auth: 'none'|'saved'|'relay'|'manual', login}.
 * `login: true` means the relay had no session either: the tab is reopened headed (guard installed again) and the
 * caller must ask the user to sign in there, then call waitLogin().
 */
export async function openApp(browser, { url, dataDir, mode = 'readonly', allowPost = [], name = 'explore', viewport = VIEWPORT } = {}) {
  const opts = { url, dataDir, mode, allowPost, name, viewport };
  const authPath = join(dataDir, 'auth.json');
  let { tab, saved } = await openGuarded(browser, opts);
  let auth = saved ? 'saved' : 'none';
  if (await isLogin(tab)) {
    const relay = await browser.open({ name: `${name}-auth`, url, app: { relay: true } });
    try {
      await quiet(relay, { render: RENDER_MS });
      await relay.saveState(authPath);
    } finally {
      await browser.close({ name: `${name}-auth` });
    }
    await tab.loadState(authPath);
    await settle(tab, url);
    auth = 'relay';
    if (await isLogin(tab)) {
      await browser.close({ name });
      ({ tab } = await openGuarded(browser, { ...opts, headed: true }));
      return { tab, lang: await langOf(tab), auth: 'manual', login: true };
    }
  }
  return { tab, lang: await langOf(tab), auth, login: false };
}

/** After the user signed in in the headed tab: wait until the login wall is gone, save <data>/auth.json. */
export async function waitLogin(tab, { dataDir, timeout = 10 * 60_000 } = {}) {
  const t0 = Date.now();
  while (await isLogin(tab)) {
    if (Date.now() - t0 > timeout) throw new Error('app-explore: still on the login page after waiting');
    await sleep(1000);
  }
  await quiet(tab, { render: RENDER_MS });
  await tab.saveState(join(dataDir, 'auth.json'));
  return { lang: await langOf(tab) };
}

async function langOf(tab) {
  const l = String(await tab.evaluate('document.documentElement.lang || ""')).toLowerCase();
  return l.startsWith('de') ? 'de' : 'en';
}

const runWrites = new Map(); // run.json path → tail of its write chain: merges in this process never interleave

/**
 * Merge `patch` into <data>/run.json (shallow). `patch` may be a function `(run) => patch` for a merge that reads the
 * current value (e.g. summing run.json `models`). Writes to one run.json are serialized; returns the merged run.
 */
export async function writeRun(dataDir, patch) {
  const p = join(dataDir, 'run.json');
  const next = (runWrites.get(p) ?? Promise.resolve()).catch(() => {}).then(async () => {
    let run = {};
    try { run = JSON.parse(await readFile(p, 'utf8')); } catch {}
    Object.assign(run, typeof patch === 'function' ? patch(run) : patch);
    await mkdir(dataDir, { recursive: true });
    await writeFile(`${p}.tmp`, JSON.stringify(run, null, 2));
    await rename(`${p}.tmp`, p);
    return run;
  });
  runWrites.set(p, next);
  return next;
}

// ---------------------------------------------------------------- in-page scripts

// Shared helpers injected before page scripts that need them.
const PAGE_LIB = `
const __vis = (el) => {
  const r = el.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) return false;
  const cs = getComputedStyle(el);
  return cs.visibility !== 'hidden' && cs.display !== 'none' && Number(cs.opacity) > 0;
};
const __role = (el) => {
  const r = el.getAttribute('role');
  if (r) return r;
  const t = el.tagName.toLowerCase();
  if (t === 'a') return 'link';
  if (t === 'button' || t === 'summary') return 'button';
  if (t === 'select') return 'combobox';
  if (t === 'textarea') return 'textbox';
  if (t === 'input') {
    const ty = (el.getAttribute('type') || 'text').toLowerCase();
    return { checkbox: 'checkbox', radio: 'radio', button: 'button', submit: 'button', reset: 'button', range: 'slider', search: 'searchbox' }[ty] || 'textbox';
  }
  return t;
};
const __label = (el) => {
  const clean = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
  let s = clean(el.getAttribute('aria-label'));
  if (!s && el.getAttribute('aria-labelledby')) s = clean(el.getAttribute('aria-labelledby').split(/\\s+/).map((id) => document.getElementById(id)?.innerText).join(' '));
  if (!s && el.labels && el.labels.length) s = clean(el.labels[0].innerText);
  if (!s && !/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) s = clean(el.innerText);
  if (!s) s = clean(el.getAttribute('title') || el.getAttribute('placeholder') || el.querySelector?.('img[alt]')?.getAttribute('alt') || el.querySelector?.('svg title')?.textContent || el.getAttribute('name') || (el.type === 'submit' || el.type === 'button' ? el.value : ''));
  return s.slice(0, 80);
};
const __heading = (root) => {
  for (const sel of ['h1', 'h2', '[role=heading]', 'h3']) {
    // Visually hidden (sr-only, 1 px) headings name nothing the user sees.
    const h = [...root.querySelectorAll(sel)].find((e) => { const r = e.getBoundingClientRect(); return __vis(e) && r.width > 4 && r.height > 4; });
    if (h && h.innerText.trim()) return h.innerText.replace(/\\s+/g, ' ').trim().slice(0, 120);
  }
  return root === document ? document.title : (root.getAttribute('aria-label') || '');
};
const __OPEN = '[role=dialog], [role=alertdialog], dialog[open], [role=menu]';
`;

const INTERACTIVE = 'a[href], button, [role=button], [role=tab], [role=menuitem], [role=link], [role=checkbox], [role=switch], input:not([type=hidden]), select, textarea, summary';

/**
 * Set-of-Mark: draw numbered boxes over visible interactive elements in the viewport (inside `within` when given)
 * and tag each with data-apx-mark. Returns [{n, role, label, box: {x,y,w,h} in viewport percent, href?}].
 */
export async function marks(tab, { within = null } = {}) {
  return tab.evaluate(`(() => {
    ${PAGE_LIB}
    document.getElementById('__apx_marks')?.remove();
    document.querySelectorAll('[data-apx-mark]').forEach((e) => e.removeAttribute('data-apx-mark'));
    const root = ${within ? `document.querySelector(${JSON.stringify(within)}) || document` : 'document'};
    const W = innerWidth, H = innerHeight;
    const layer = document.createElement('div');
    layer.id = '__apx_marks';
    layer.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;max-width:none;max-height:none;margin:0;padding:0;' +
      'border:0;background:transparent;overflow:visible;pointer-events:none;z-index:2147483647';
    const out = [];
    for (const el of root.querySelectorAll(${JSON.stringify(INTERACTIVE)})) {
      if (!__vis(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.bottom <= 0 || r.right <= 0 || r.top >= H || r.left >= W) continue;
      const n = out.length + 1;
      el.setAttribute('data-apx-mark', n);
      const box = document.createElement('div');
      box.style.cssText = 'position:fixed;border:2px solid #e5197e;box-sizing:border-box;' +
        'left:' + r.left + 'px;top:' + r.top + 'px;width:' + r.width + 'px;height:' + r.height + 'px';
      const tag = document.createElement('span');
      tag.textContent = n;
      tag.style.cssText = 'position:absolute;left:-2px;top:-2px;transform:translateY(-100%);background:#e5197e;color:#fff;' +
        'font:bold 11px/14px system-ui,sans-serif;padding:0 3px;border-radius:2px';
      if (r.top < 16) tag.style.transform = 'none';
      box.appendChild(tag);
      layer.appendChild(box);
      const pct = (v, d) => Math.round(v / d * 1000) / 10;
      const m = { n, role: __role(el), label: __label(el),
        box: { x: pct(r.left, W), y: pct(r.top, H), w: pct(r.width, W), h: pct(r.height, H) } };
      if (el.tagName === 'A' && el.href) m.href = el.href;
      out.push(m);
    }
    document.documentElement.appendChild(layer);
    // A popover sits in the top layer above modal <dialog>s, so marks stay visible over them.
    if (layer.showPopover) { layer.popover = 'manual'; layer.showPopover(); }
    return out;
  })()`);
}

/** Remove the mark overlay and the data-apx-mark tags. */
export async function unmark(tab) {
  await tab.evaluate(`(() => {
    document.getElementById('__apx_marks')?.remove();
    document.querySelectorAll('[data-apx-mark]').forEach((e) => e.removeAttribute('data-apx-mark'));
  })()`);
}

/**
 * DOM geometry checks on the current marks (call between marks() and unmark()):
 * overflow = marks whose element or a descendant text container clips its text (scrollWidth > clientWidth + 1,
 * overflow visible/hidden); overlap = mark pairs intersecting > 20 % of the smaller box (nested elements excluded);
 * small_targets = marks under 24×24 CSS px (WCAG 2.5.8; inline text links exempt).
 */
export async function geometry(tab, list) {
  const ns = list.map((m) => m.n);
  return tab.evaluate(`(() => {
    const ns = ${JSON.stringify(ns)};
    const els = ns.map((n) => [n, document.querySelector('[data-apx-mark="' + n + '"]')]).filter(([, e]) => e);
    const clips = (e) => {
      if (e.scrollWidth <= e.clientWidth + 1 || e.clientWidth === 0) return false;
      const ox = getComputedStyle(e).overflowX;
      if (ox !== 'visible' && ox !== 'hidden' && ox !== 'clip') return false;
      return [...e.childNodes].some((c) => c.nodeType === 3 && c.textContent.trim());
    };
    const overflow = [], small = [], overlap = [];
    for (const [n, e] of els) {
      if (clips(e) || [...e.querySelectorAll('*')].some(clips)) overflow.push(n);
      const r = e.getBoundingClientRect();
      const inline = e.tagName === 'A' && getComputedStyle(e).display === 'inline';
      if (!inline && (r.width < 24 || r.height < 24)) small.push(n);
    }
    for (let i = 0; i < els.length; i++) {
      const [n, a] = els[i], ra = a.getBoundingClientRect();
      for (let j = i + 1; j < els.length; j++) {
        const [m, b] = els[j];
        if (a.contains(b) || b.contains(a)) continue;
        const rb = b.getBoundingClientRect();
        const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
        const h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
        if (w <= 0 || h <= 0) continue;
        const smaller = Math.min(ra.width * ra.height, rb.width * rb.height);
        if (smaller > 0 && (w * h) / smaller > 0.2) overlap.push([n, m]);
      }
    }
    return { overflow, overlap, small_targets: small };
  })()`);
}

/**
 * 64-bit difference hash of a PNG file as 16 hex chars: grayscale, area-averaged to 9×8, bit = left < right.
 * Decoded in Bun (8-bit, non-interlaced PNG as Chromium writes them), so page CSP never interferes.
 */
export async function dhash(pngPath) {
  const buf = await readFile(pngPath);
  let off = 8, w = 0, h = 0, depth = 8, ctype = 6, interlace = 0;
  const idat = [];
  while (off < buf.length) {
    const len = buf.readUInt32BE(off);
    const type = buf.toString('latin1', off + 4, off + 8);
    const data = buf.subarray(off + 8, off + 8 + len);
    if (type === 'IHDR') { w = data.readUInt32BE(0); h = data.readUInt32BE(4); depth = data[8]; ctype = data[9]; interlace = data[12]; }
    else if (type === 'IDAT') idat.push(data);
    else if (type === 'IEND') break;
    off += 12 + len;
  }
  if (depth !== 8 || interlace) throw new Error(`dhash: unsupported PNG (bit depth ${depth}, interlace ${interlace}): ${pngPath}`);
  const bpp = { 0: 1, 2: 3, 4: 2, 6: 4 }[ctype];
  if (!bpp) throw new Error(`dhash: unsupported PNG colour type ${ctype}: ${pngPath}`);
  const raw = inflateSync(Buffer.concat(idat));
  const stride = w * bpp;
  const px = Buffer.alloc(stride * h);
  for (let y = 0; y < h; y++) {
    const f = raw[y * (stride + 1)];
    const src = y * (stride + 1) + 1, dst = y * stride, up = dst - stride;
    for (let x = 0; x < stride; x++) {
      const a = x >= bpp ? px[dst + x - bpp] : 0;
      const b = y ? px[up + x] : 0;
      const c = y && x >= bpp ? px[up + x - bpp] : 0;
      let v = raw[src + x];
      if (f === 1) v += a;
      else if (f === 2) v += b;
      else if (f === 3) v += (a + b) >> 1;
      else if (f === 4) { const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c); v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c; }
      px[dst + x] = v & 255;
    }
  }
  const GW = 9, GH = 8;
  const sum = new Float64Array(GW * GH), cnt = new Float64Array(GW * GH);
  for (let y = 0; y < h; y++) {
    const gy = Math.min(GH - 1, Math.floor((y * GH) / h));
    for (let x = 0; x < w; x++) {
      const gx = Math.min(GW - 1, Math.floor((x * GW) / w));
      const i = y * stride + x * bpp;
      const g = bpp >= 3 ? 0.299 * px[i] + 0.587 * px[i + 1] + 0.114 * px[i + 2] : px[i];
      sum[gy * GW + gx] += g; cnt[gy * GW + gx] += 1;
    }
  }
  let hex = '';
  for (let y = 0; y < GH; y++) {
    let byte = 0;
    for (let x = 0; x < 8; x++) {
      const l = sum[y * GW + x] / cnt[y * GW + x], r = sum[y * GW + x + 1] / cnt[y * GW + x + 1];
      byte = (byte << 1) | (l < r ? 1 : 0);
    }
    hex += byte.toString(16).padStart(2, '0');
  }
  return hex;
}

// ---------------------------------------------------------------- crawl

// Candidate actions on the current page, in crawl order. Tags each with data-apx-c=<i> for clicking.
async function candidates(tab, within = null) {
  return tab.evaluate(`(() => {
    ${PAGE_LIB}
    document.querySelectorAll('[data-apx-c]').forEach((e) => e.removeAttribute('data-apx-c'));
    const root = ${within ? `document.querySelector(${JSON.stringify(within)}) || document` : 'document'};
    const NAV = 'nav, header, aside, [role=navigation]';
    const seen = new Set(), out = [];
    const add = (el, cat) => {
      if (seen.has(el) || !__vis(el)) return;
      seen.add(el);
      const i = out.length;
      el.setAttribute('data-apx-c', i);
      const c = { i, cat, role: __role(el), label: __label(el), tag: el.tagName.toLowerCase() };
      if (el.tagName === 'A') { c.href = el.href; c.download = el.hasAttribute('download'); c.target = el.target; }
      c.submit = (el.tagName === 'BUTTON' && (el.getAttribute('type') || (el.form ? 'submit' : 'button')) === 'submit') || (el.tagName === 'INPUT' && el.type === 'submit');
      c.selected = el.getAttribute('aria-selected') === 'true';
      out.push(c);
    };
    const q = (s) => [...root.querySelectorAll(s)];
    q('a[href]').filter((e) => e.closest(NAV)).forEach((e) => add(e, 'nav'));
    q('a[href]').forEach((e) => add(e, 'link'));
    q('[role=tab]').forEach((e) => add(e, 'tab'));
    q('[aria-haspopup]:not([aria-haspopup=false]), [aria-expanded]').forEach((e) => add(e, 'popup'));
    q('button, [role=button], summary, input[type=button], input[type=submit]').forEach((e) => add(e, 'button'));
    return out;
  })()`);
}

// Facts about the current page (or the open dialog/menu `within`) used for the state key.
async function facts(tab, within = null) {
  return tab.evaluate(`(() => {
    ${PAGE_LIB}
    const root = ${within ? `document.querySelector(${JSON.stringify(within)}) || document` : 'document'};
    const labels = [...new Set([...root.querySelectorAll(${JSON.stringify(INTERACTIVE)})].filter(__vis).map(__label).filter(Boolean))].sort();
    return { title: document.title, heading: __heading(root), labels };
  })()`);
}

// Tag the visible open dialogs/menus; after a click, the untagged visible one is the new state.
async function tagOpen(tab) {
  await tab.evaluate(`(() => { ${PAGE_LIB}
    document.querySelectorAll(__OPEN).forEach((e) => { if (__vis(e)) e.setAttribute('data-apx-was', '1'); });
  })()`);
}
async function newOpen(tab) {
  return tab.evaluate(`(() => { ${PAGE_LIB}
    document.querySelectorAll('[data-apx-open]').forEach((e) => e.removeAttribute('data-apx-open'));
    const el = [...document.querySelectorAll(__OPEN)].find((e) => __vis(e) && !e.hasAttribute('data-apx-was'));
    if (!el) return null;
    el.setAttribute('data-apx-open', '1');
    const role = el.getAttribute('role') || 'dialog';
    return role === 'menu' ? 'menu' : 'dialog';
  })()`);
}
async function stillOpen(tab) {
  return tab.evaluate(`(() => { ${PAGE_LIB} const e = document.querySelector('[data-apx-open]'); return !!(e && e.isConnected && __vis(e)); })()`);
}
async function selectedTab(tab) {
  return tab.evaluate(`(() => [...document.querySelectorAll('[role=tab][aria-selected=true]')].map((e) => e.innerText.trim()).join('|'))()`);
}

const SKIP_EXT = /\.(pdf|zip|gz|tgz|csv|xlsx?|docx?|pptx?|png|jpe?g|gif|svg|webp|mp4|mov|mp3|dmg|exe|ics|json|xml)(\?|$)/i;
const CLOSE = /^(close|schließen|cancel|abbrechen|×|x|✕)$/i;

/**
 * Breadth-first crawl into <data>/graph.json (rewritten after every state), <media>/<id>.png, <id>.som.png,
 * <id>.mobile.png (depth ≤ 1 pages) and <data>/screens/<id>.json. Pages are expanded by goto; dialogs, menus and
 * tab panels opened by a click are leaf states whose same-origin links are queued as pages. Seeds (previous run
 * URLs) are visited right after `start`. Returns counts; `stopped` holds the error when the tab died mid-crawl
 * (a page whose script froze the tab): every state captured before it is already on disk.
 */
export async function crawl(tab, {
  dataDir, mediaDir, start, mode = 'readonly', seeds = [],
  budgets = {}, log = () => {},
} = {}) {
  const B = { states: 60, depth: 5, perRoute: 2, actions: 25, minutes: 20, ...budgets };
  const t0 = Date.now();
  const late = () => Date.now() - t0 > B.minutes * 60_000;
  const origin = new URL(start).origin;
  const media = basename(mediaDir);
  await mkdir(join(dataDir, 'screens'), { recursive: true });
  await mkdir(mediaDir, { recursive: true });
  for (const f of ['blocked.jsonl', 'passive.jsonl', 'leaks.jsonl']) await appendFile(join(dataDir, f), '');
  await tab.setDialogs('dismiss');

  const states = [];
  const byKey = new Map();
  const byRoute = new Map(); // route → [state]
  const urlState = new Map(); // normalized url → state id
  const linkEdges = []; // {from, url, label, mark} resolved through urlState
  const edges = [];
  const queued = new Set();
  const queue = [];
  let seq = await lastSeq(tab);
  let skipped = 0;
  let here = null; // id of the last captured page: the state whose page produced the guard rows drained next
  const pad = (n) => `s${String(n).padStart(2, '0')}`;

  const enqueue = (href, parent, via, depth) => {
    let u;
    try { u = normUrl(href); } catch { return false; }
    if (new URL(u).origin !== origin) return false;
    if (parent) linkEdges.push({ from: parent, url: u, label: via.label ?? null, mark: via.mark ?? null });
    if (queued.has(u)) return false;
    queued.add(u);
    queue.push({ url: u, parent, via, depth });
    return true;
  };

  const save = async () => {
    const all = [...edges];
    for (const e of linkEdges) {
      const to = urlState.get(e.url);
      if (to && to !== e.from) all.push({ from: e.from, to, label: e.label, mark: e.mark });
    }
    const seen = new Set();
    const uniq = all.filter((e) => { const k = `${e.from}>${e.to}>${e.label}`; if (seen.has(k)) return false; seen.add(k); return true; });
    // Click depth = BFS distance from the first state over the edges; unreachable states keep their discovery depth.
    if (states.length) {
      const d = new Map([[states[0].id, 0]]);
      const q = [states[0].id];
      while (q.length) {
        const s = q.shift();
        for (const e of uniq) if (e.from === s && !d.has(e.to)) { d.set(e.to, d.get(s) + 1); q.push(e.to); }
      }
      for (const s of states) if (d.has(s.id)) s.depth = d.get(s.id);
    }
    await writeFile(join(dataDir, 'graph.json'), JSON.stringify({ states, edges: uniq }, null, 2));
  };

  const shot = async (name) => {
    const p = await tab.screenshot({ silent: true, format: 'png' });
    await copyFile(p, join(mediaDir, name));
    return `${media}/${name}`;
  };

  // Record the current page (kind page) or the open dialog/menu/tab panel as a state; null when known or capped.
  // Dialogs and menus key without their route: the same account menu opened on every page is one state.
  const capture = async ({ kind, parent, via, depth, within = null, headingSuffix = '' }) => {
    const url = await tab.url();
    const route = routeOf(url);
    const f = await facts(tab, within);
    const heading = ((f.heading || (within ? via.label || '' : '')) + headingSuffix).trim();
    const keyRoute = kind === 'dialog' || kind === 'menu' ? '*' : route;
    const key = createHash('sha1').update([keyRoute, kind, heading, f.labels.join('\u0001')].join('|')).digest('hex');
    const known = byKey.get(key);
    if (known) return { state: known, fresh: false };
    const same = (byRoute.get(`${kind}:${route}`) || []);
    if (same.length >= B.perRoute) {
      same[same.length - 1].instances += 1;
      skipped += 1;
      return { state: same[same.length - 1], fresh: false };
    }
    const id = pad(states.length + 1);
    const s = { id, key, url, route, kind, title: f.title, heading, depth, parent: parent ?? null, via, instances: 1 };
    s.shot = await shot(`${id}.png`);
    const text = String(await tab.evaluate(`(document.querySelector(${JSON.stringify(within || 'body')}) || document.body).innerText`) || '').slice(0, 4000);
    let aria = '';
    try { aria = String(await tab.ariaSnapshot(within, { compact: true }) || ''); } catch { try { aria = String(await tab.ariaSnapshot(null, { compact: true }) || ''); } catch {} }
    const m = await marks(tab, { within });
    const geo = await geometry(tab, m);
    s.som = await shot(`${id}.som.png`);
    await unmark(tab);
    s.hash = await dhash(join(mediaDir, `${id}.png`));
    if (kind === 'page' && depth <= 1) {
      await tab.emulate({ viewport: { width: 390, height: 844 } });
      await sleep(300);
      await quiet(tab, { cap: 2000 });
      s.mobile_shot = await shot(`${id}.mobile.png`);
      await tab.emulate({ viewport: VIEWPORT });
      await sleep(200);
    }
    await writeFile(join(dataDir, 'screens', `${id}.json`), JSON.stringify({ id, aria: aria.slice(0, 12000), text, marks: m, geometry: geo }, null, 2));
    states.push(s);
    byKey.set(key, s);
    same.push(s);
    byRoute.set(`${kind}:${route}`, same);
    if (kind === 'page') urlState.set(normUrl(url), id);
    log(`${id} ${kind} ${route} — ${heading}`);
    await save();
    return { state: s, fresh: true, marks: m };
  };

  const markOf = (m, c) => (m || []).find((x) => x.label === c.label && x.role === c.role && (!c.href || x.href === c.href))?.n ?? null;

  const queueLinks = async (from, depth, m, within = null) => {
    if (depth >= B.depth) return 0;
    let n = 0;
    for (const c of await candidates(tab, within)) {
      if (!c.href || (c.cat !== 'nav' && c.cat !== 'link')) continue;
      if (c.download || SKIP_EXT.test(c.href) || /^(mailto|tel|javascript):/i.test(c.href) || denied(c.label, mode, c.href)) continue;
      if (enqueue(c.href, from, { action: 'click', label: c.label, mark: markOf(m, c) }, depth + 1)) n++;
    }
    return n;
  };

  // Same-origin SPA: history.pushState skips a full page load (on an unbundled dev server that load is ~1500
  // module requests). Counts only when the page text changed and no dialog/menu was left open; else a real goto.
  // `full`: the start URL and seeds always get a real load (an app may redirect `/` only on a full load).
  const softGo = async (url) => {
    let cur = '';
    try { cur = await tab.url(); } catch {}
    if (!cur.startsWith('http') || new URL(cur).origin !== origin || normUrl(cur) === normUrl(url)) return false;
    const before = await tab.evaluate(`(() => { ${PAGE_LIB}
      return [...document.querySelectorAll(__OPEN)].some(__vis) ? null : document.body.innerText; })()`);
    if (before == null) return false;
    try { await tab.pushState(url); } catch { return false; }
    if (!(await quiet(tab, { render: RENDER_MS }))) return false;
    if ((await tab.evaluate('document.body.innerText')) === before) return false;
    await tab.evaluate('scrollTo(0, 0)');
    return true;
  };

  const goto = async (url, { full = false } = {}) => {
    await drainBlocked(tab, dataDir, { state: here });
    if (!full && await softGo(url)) return;
    try { await tab.goto(url); } catch (e) { log(`goto failed ${url}: ${e.message}`); }
    await quiet(tab, { render: RENDER_MS });
  };

  enqueue(start, null, { action: 'goto', label: null, mark: null }, 0);
  for (const s of seeds) enqueue(s, null, { action: 'goto', label: null, mark: null }, 1);

  // Clicks: tabs, popups, then other buttons. Each candidate is re-found by role|label|href|nth after a reset.
  const expand = async (page, pageUrl, pageMarks, actions) => {
    const all = await candidates(tab);
    const clicks = all.filter((c) => !c.href && ['tab', 'popup', 'button'].includes(c.cat) && !c.selected
      && !denied(c.label, mode) && !(mode === 'readonly' && c.submit) && c.label);
    const sig = (c) => `${c.cat}|${c.role}|${c.label}`;
    const nth = new Map();
    const plan = clicks.map((c) => { const k = sig(c); const i = nth.get(k) || 0; nth.set(k, i + 1); return { c, k, i }; });
    const cats = ['tab', 'popup', 'button'];
    plan.sort((a, b) => cats.indexOf(a.c.cat) - cats.indexOf(b.c.cat));
    let dirty = false;
    for (const { c, k, i } of plan) {
      if (actions >= B.actions || states.length >= B.states || late()) break;
      if (dirty) { await goto(pageUrl); dirty = false; }
      const now = (await candidates(tab)).filter((x) => sig(x) === k)[i];
      if (!now) continue;
      actions++;
      await tagOpen(tab);
      const tabBefore = c.cat === 'tab' ? await selectedTab(tab) : null;
      const sel = `[data-apx-c="${now.i}"]`;
      await act(tab);
      try { await tab.click(sel); } catch { continue; }
      await sleep(300);
      await quiet(tab, { cap: 3000 });
      const via = { action: 'click', label: c.label, mark: markOf(pageMarks, c) };
      const after = await tab.url();
      if (normUrl(after) !== normUrl(pageUrl)) {
        if (new URL(after).origin === origin) enqueue(after, page.id, via, page.depth + 1);
        dirty = true;
        continue;
      }
      const opened = await newOpen(tab);
      if (opened) {
        const d = await capture({ kind: opened, parent: page.id, via, depth: page.depth + 1, within: '[data-apx-open]' });
        if (d.state.id !== page.id) edges.push({ from: page.id, to: d.state.id, label: c.label, mark: via.mark });
        if (d.fresh) await queueLinks(d.state.id, d.state.depth, d.marks, '[data-apx-open]');
        await act(tab);
        await tab.press('Escape');
        await sleep(250);
        if (await stillOpen(tab)) {
          const close = (await candidates(tab, '[data-apx-open]')).find((x) => CLOSE.test(x.label));
          if (close) { try { await act(tab); await tab.click(`[data-apx-c="${close.i}"]`); await sleep(250); } catch {} }
          if (await stillOpen(tab)) dirty = true;
        }
      } else if (c.cat === 'tab' && (await selectedTab(tab)) !== tabBefore) {
        const d = await capture({ kind: 'tab', parent: page.id, via, depth: page.depth + 1, headingSuffix: ` › ${c.label}` });
        if (d.state.id !== page.id) edges.push({ from: page.id, to: d.state.id, label: c.label, mark: via.mark });
        if (d.fresh) await queueLinks(d.state.id, d.state.depth, d.marks);
      }
      if (mode === 'readonly') seq = await auditLeaks(tab, dataDir, seq, { state: page.id });
      await drainBlocked(tab, dataDir, { state: page.id });
    }
  };

  let stopped = null;
  try {
  while (queue.length && states.length < B.states && !late()) {
    const item = queue.shift();
    if (item.expand) {
      // Deferred click expansion of the start page or a seed: back to its URL, then click through it.
      await goto(item.url, { full: true });
      if (normUrl(await tab.url()) !== normUrl(item.url)) continue;
      here = item.expand.id;
      await expand(item.expand, item.url, item.marks, item.actions);
      continue;
    }
    await goto(item.url, { full: !item.parent });
    const landed = await tab.url();
    if (new URL(landed).origin !== origin) { log(`left origin: ${item.url} → ${landed}`); continue; }
    const r = await capture({ kind: 'page', parent: item.parent, via: item.via, depth: item.depth });
    urlState.set(item.url, r.state.id);
    urlState.set(normUrl(landed), r.state.id);
    here = r.state.id;
    if (mode === 'readonly') seq = await auditLeaks(tab, dataDir, seq, { state: r.state.id });
    await drainBlocked(tab, dataDir, { state: r.state.id });
    if (!r.fresh) continue;
    const page = r.state;
    const pageUrl = await tab.url();
    const actions = await queueLinks(page.id, page.depth, r.marks);
    // Seeds are visited right after the start page: while a seed page or a deferred expansion is still queued, this
    // page's in-page clicks (start page and seeds alike) wait behind them, in visit order, instead of spending the
    // state budget before the seeds are reached.
    const last = queue.findLastIndex((x) => !x.parent);
    if (last >= 0) {
      queue.splice(last + 1, 0, { expand: page, url: pageUrl, marks: r.marks, actions });
      continue;
    }
    await expand(page, pageUrl, r.marks, actions);
  }
  } catch (e) {
    stopped = `${e.message} (after ${states.length} states)`;
    log(`crawl stopped: ${stopped}`);
  }
  await save();
  const kinds = {};
  for (const s of states) kinds[s.kind] = (kinds[s.kind] || 0) + 1;
  const lines = async (f) => { try { return (await readFile(join(dataDir, f), 'utf8')).split('\n').filter(Boolean).length; } catch { return 0; } };
  const blocked = (await readFile(join(dataDir, 'blocked.jsonl'), 'utf8').catch(() => '')).split('\n').filter(Boolean)
    .filter((l) => JSON.parse(l).why !== 'selfcheck').length;
  const leaks = await lines('leaks.jsonl');
  return { states: states.length, kinds, edges: JSON.parse(await readFile(join(dataDir, 'graph.json'), 'utf8')).edges.length,
    queued: queue.length, skipped, blocked, leaks, minutes: Math.round((Date.now() - t0) / 6000) / 10, stopped };
}
