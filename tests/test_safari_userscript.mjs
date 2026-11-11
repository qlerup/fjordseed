/**
 * Offline userscript contract checks. These exercise the real bundled sources
 * with mock GM storage and tracker responses, not an iPhone or Safari renderer.
 * Install happy-dom outside the repo and set FJORDSEED_TEST_HAPPY_DOM to its
 * lib/index.js path, or make the package available to Node's module resolver.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const {Window} = await import(process.env.FJORDSEED_TEST_HAPPY_DOM || 'happy-dom');
const common = () => fs.readFileSync(path.join(root, 'chrome-extension/common.mjs'), 'utf8').replace(/^export /gm, '');
const source = name => fs.readFileSync(path.join(root, 'safari-userscript', name), 'utf8');
const SEED = 'https://seed.example.test:8443';
const TRACKER = 'https://nordicbytes.org';
const PREFIX = 'fjordseed:pending:';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(condition, timeout = 2000) {
  const end = Date.now() + timeout;
  while (!condition()) {
    if (Date.now() >= end) throw Error('Expected userscript state was not reached.');
    await delay(10);
  }
}

function storage() {
  const values = new Map();
  return {
    values,
    async getValue(key, fallback) { return structuredClone(values.has(key) ? values.get(key) : fallback); },
    async setValue(key, value) { values.set(key, structuredClone(value)); },
    async deleteValue(key) { values.delete(key); },
    async listValues() { return [...values.keys()]; },
    pending() { return [...values].filter(([key]) => key.startsWith(PREFIX)); }
  };
}

function fixture(t, {url = TRACKER + '/torrents', store = storage(), gm = true} = {}) {
  const window = new Window({url, settings: {enableJavaScriptEvaluation: true,
    disableCSSFileLoading: true, disableJavaScriptFileLoading: true,
    suppressInsecureJavaScriptEnvironmentWarning: true}});
  const opened = [], requests = [], deliveries = [];
  window.document.body.innerHTML = '<form id="add-form"></form>';
  let api;
  if (gm) window.GM = {
    getValue: store.getValue, setValue: store.setValue,
    deleteValue: store.deleteValue, listValues: store.listValues,
    openInTab: async (address, options) => { opened.push({address, options}); }
  };
  window.mountFjordSeedPanel = adapter => { api = adapter; };
  window.fetch = async (address, options) => {
    requests.push({address: String(address), options});
    return new window.Response('d1:xe', {headers: {'Content-Type': 'application/x-bittorrent'}});
  };
  window.eval(common() + '\n' + source('runtime.js'));
  // The shared normal-dialog helpers are already tested independently. Here
  // their calls prove which route the receiver chooses and what it forwards.
  window.showTorrent = async (...args) => { deliveries.push({kind: 'torrent', args}); return 'delivered'; };
  window.showRss = (...args) => { deliveries.push({kind: 'rss', args}); return 'delivered'; };
  window.stageTorrent = async (...args) => { deliveries.push({kind: 'package', args}); return {status: 'stored', count: 1}; };
  let controller;
  t.after(async () => { controller?.stop?.(); await window.happyDOM.close(); });
  return {window, store, opened, requests, deliveries,
    get api() { return api; },
    async start(origin = SEED) { controller = await window.startFjordSeedUserscript(origin, ''); return controller; },
    poll() { window.dispatchEvent(new window.Event('focus')); }
  };
}

test('actual public generator emits a parsable, narrowly matched single userscript', () => {
  const script = execFileSync('python', ['-c',
    'import sys; from safari_setup import build_userscript; print(build_userscript(sys.argv[1]))', SEED],
    {cwd: root, encoding: 'utf8'});
  assert.doesNotThrow(() => new vm.Script(script));
  const matches = script.split('\n').filter(line => /^\/\/\s*@match\s/.test(line));
  assert(matches.some(line => line.includes('https://nordicbytes.org/*')));
  assert(matches.some(line => line.includes('https://sagmire.org/*')));
  // Match patterns are host-scoped; the runtime checks the exact port.
  assert(matches.some(line => line.includes('https://seed.example.test/*')));
  assert(!matches.some(line => line.includes('<all_urls>') || line.includes('*://*/*')));
  assert.match(script, /@grant\s+GM\.getValue/);
  assert.match(script, /@grant\s+GM\.setValue/);
  assert.match(script, /@grant\s+GM\.deleteValue/);
  assert.match(script, /@grant\s+GM\.listValues/);
  assert.match(script, /@grant\s+GM\.openInTab/);
  assert(!/^export /m.test(script));
});

test('torrent transfer fetches only its exact tracker URL and opens only the Seed origin', async t => {
  const tracker = fixture(t);
  await tracker.start();
  const link = TRACKER + '/torrents/download/42?key=fixture-private';
  const result = await tracker.api.runtime.sendMessage({type: 'send-link', url: link});
  assert.equal(result.ok, true);
  assert.equal(tracker.requests.length, 1);
  assert.equal(tracker.requests[0].address, link);
  assert.equal(tracker.requests[0].options.credentials, 'include');
  assert.equal(tracker.requests[0].options.redirect, 'error');
  assert.deepEqual(tracker.opened.map(item => item.address), [SEED]);
  const [[key, record]] = tracker.store.pending();
  assert.equal(key, PREFIX + record.id);
  assert.equal(record.seedOrigin, SEED);
  assert.equal(record.kind, 'torrent');
  assert.equal(record.sourceOrigin, TRACKER);
  assert.equal(record.sourcePath, '/torrents/download/42');
  assert.equal(record.name, 'NordicBytes-42.torrent');
  assert.equal(Buffer.from(record.base64, 'base64').toString(), 'd1:xe');
  assert.equal(record.expires - record.created, 15 * 60 * 1000);
  assert(!JSON.stringify(tracker.opened).includes('fixture-private'));
  assert(!JSON.stringify(record).includes('fixture-private'));
});

test('cross-origin, wrong-host, non-download and RSS-package selections never fetch', async t => {
  const tracker = fixture(t);
  await tracker.start();
  for (const url of ['https://sagmire.org/torrents/download/42',
    'https://nordicbytes.org.evil.test/torrents/download/42',
    TRACKER + ':444/torrents/download/42', TRACKER + '/torrents/42',
    'javascript:alert(1)', TRACKER + '/rss/manage/42']) {
    const result = await tracker.api.runtime.sendMessage({type: 'send-link', url});
    assert(result.error, url);
  }
  const rssPackage = await tracker.api.runtime.sendMessage({type: 'package-add', url: TRACKER + '/rss/42?key=fixture'});
  assert(rssPackage.error);
  assert.equal(tracker.requests.length, 0);
  assert.equal(tracker.opened.length, 0);
  assert.equal(tracker.store.pending().length, 0);
});

test('RSS keeps the full address in its record, never fetches it, and reaches only the RSS dialog', async t => {
  const store = storage(), tracker = fixture(t, {store});
  await tracker.start();
  const url = TRACKER + '/rss/42?passkey=fixture-private&freeleech=1';
  const result = await tracker.api.runtime.sendMessage({type: 'send-link', url});
  assert.equal(result.ok, true);
  assert.equal(tracker.requests.length, 0);
  assert.deepEqual(tracker.opened.map(item => item.address), [SEED]);
  assert.equal(store.pending()[0][1].url, url);
  const seed = fixture(t, {url: SEED + '/', store});
  await seed.start();
  await until(() => seed.deliveries.length === 1);
  assert.equal(seed.deliveries[0].kind, 'rss');
  assert.equal(seed.deliveries[0].args[0], url);
  assert.equal(seed.deliveries[0].args[2], SEED);
  await until(() => store.pending().length === 0);
  assert.equal(seed.requests.length, 0);
  assert.equal(seed.window.location.href, SEED + '/');
});

test('concurrent selections have independent records and package handling only stages a draft', async t => {
  const store = storage(), first = fixture(t, {store}), second = fixture(t, {store});
  await Promise.all([first.start(), second.start()]);
  const results = await Promise.all([
    first.api.runtime.sendMessage({type: 'package-add', url: TRACKER + '/torrents/download/41'}),
    second.api.runtime.sendMessage({type: 'package-add', url: TRACKER + '/torrents/download/42'})
  ]);
  assert(results.every(result => result.ok));
  assert.equal(store.pending().length, 2);
  assert.equal(new Set(store.pending().map(([key]) => key)).size, 2);
  assert.equal(first.opened.length + second.opened.length, 0);
  const seed = fixture(t, {url: SEED + '/', store});
  await seed.start();
  await until(() => seed.deliveries.length === 2);
  assert(seed.deliveries.every(item => item.kind === 'package'));
  assert.deepEqual(new Set(seed.deliveries.map(item => item.args[1])),
    new Set(['NordicBytes-41.torrent', 'NordicBytes-42.torrent']));
  assert(seed.deliveries.every(item => item.args[2] === SEED));
  await until(() => store.pending().length === 0);
  assert.equal(seed.requests.length, 0);
});

test('login or an open dialog keeps a handoff available for a later receiver attempt', async t => {
  const store = storage(), tracker = fixture(t, {store});
  await tracker.start();
  await tracker.api.runtime.sendMessage({type: 'send-link', url: TRACKER + '/torrents/download/42'});
  const seed = fixture(t, {url: SEED + '/', store});
  let calls = 0;
  seed.window.showTorrent = async () => { calls++; return 'login'; };
  await seed.start();
  await until(() => calls >= 1);
  assert.equal(store.pending().length, 1);
  seed.window.showTorrent = async () => { calls++; return 'busy'; };
  seed.poll();
  await until(() => calls >= 2);
  assert.equal(store.pending().length, 1);
  seed.window.showTorrent = async () => { calls++; return 'delivered'; };
  seed.poll();
  await until(() => store.pending().length === 0);
});

test('wrong seed ports cannot consume another instance\'s records', async t => {
  const store = storage(), tracker = fixture(t, {store});
  await tracker.start();
  await tracker.api.runtime.sendMessage({type: 'send-link', url: TRACKER + '/rss/42?key=fixture'});
  const wrongSeed = fixture(t, {url: 'https://seed.example.test:8444/', store});
  await wrongSeed.start();
  wrongSeed.poll();
  await delay(100);
  assert.equal(wrongSeed.deliveries.length, 0);
  assert.equal(wrongSeed.requests.length, 0);
  assert.equal(store.pending().length, 1);
});

test('an expired or malformed stored handoff cannot reach a Seed dialog', async t => {
  const store = storage(), tracker = fixture(t, {store});
  await tracker.start();
  await tracker.api.runtime.sendMessage({type: 'send-link', url: TRACKER + '/rss/42?key=fixture'});
  const [key, valid] = store.pending()[0];
  store.values.set(key, {...valid, created: Date.now() - 16 * 60 * 1000, expires: Date.now() - 60 * 1000});
  const seed = fixture(t, {url: SEED + '/', store});
  await seed.start();
  await delay(100);
  assert.equal(seed.deliveries.length, 0);
  assert.equal(seed.requests.length, 0);
  store.values.set(key, {...valid, sourceOrigin: 'https://evil.example', url: 'https://evil.example/rss/42'});
  seed.poll();
  await delay(100);
  assert.equal(seed.deliveries.length, 0);
  store.values.set(key, {...valid, kind: 'package', base64: btoa('de'), name: 'fixture.torrent'});
  seed.poll();
  await delay(100);
  assert.equal(seed.deliveries.length, 0);
});

test('missing Userscripts GM support produces a visible setup error', async t => {
  const tracker = fixture(t, {gm: false});
  await tracker.start();
  const notice = tracker.window.document.querySelector('fjordseed-userscript-status');
  assert(notice);
  assert.match(notice.shadowRoot.textContent, /Userscripts|GM|tilladelse/i);
  assert.equal(tracker.api, undefined);
  assert.equal(tracker.requests.length, 0);
});

test('the real panel follows exact links and rejects synthetic selections', async t => {
  const window = new Window({url: TRACKER + '/torrents', settings: {enableJavaScriptEvaluation: true,
    disableCSSFileLoading: true, disableJavaScriptFileLoading: true,
    suppressInsecureJavaScriptEnvironmentWarning: true}});
  t.after(() => window.happyDOM.close());
  window.document.body.innerHTML = '<main id="links"></main>';
  window.eval(common() + '\n' + source('panel.js'));
  const messages = [], listeners = [];
  const api = {runtime: {sendMessage: async message => { messages.push(message); return {ok: true}; }},
    storage: {local: {get: async () => ({showButtons: true})},
      onChanged: {addListener: listener => listeners.push(listener)}}};
  window.mountFjordSeedPanel(api, source('panel.css'));
  await delay(180);
  assert.equal(window.document.querySelector('fjordseed-safari-panel'), null);
  window.document.querySelector('#links').innerHTML =
    '<a id="torrent" href="/torrents/download/42?key=fixture-private">Fixture title</a>' +
    '<a id="rss" href="/rss/42?passkey=fixture-private">token=fixture-private</a>' +
    '<a href="https://sagmire.org/torrents/download/42">Different tracker</a>' +
    '<a href="https://nordicbytes.org.evil.test/torrents/download/42">Wrong host</a>';
  await delay(180);
  const host = window.document.querySelector('fjordseed-safari-panel'), shadow = host.shadowRoot;
  assert.equal(shadow.querySelectorAll('.link-card').length, 2);
  assert.equal(shadow.querySelector('.link-label').textContent, 'Fixture title');
  assert(!shadow.textContent.includes('fixture-private'));
  assert.equal(shadow.querySelectorAll('.link-card')[1].querySelectorAll('button').length, 1);
  shadow.querySelector('.fjordseed-tab').click();
  assert(shadow.querySelector('.fjordseed-panel').hidden);
  shadow.querySelector('.link-actions button').click();
  window.document.querySelector('#torrent').dispatchEvent(new window.PointerEvent('pointerdown',
    {bubbles: true, pointerType: 'touch', isPrimary: true, button: 0, clientX: 10, clientY: 10}));
  await delay(650);
  assert(shadow.querySelector('.fjordseed-panel').hidden);
  assert.equal(messages.length, 0);
  window.document.querySelector('#torrent').href = '/help';
  await delay(180);
  assert.equal(shadow.querySelectorAll('.link-card').length, 1);
  assert(!window.document.querySelector('#torrent').classList.contains('fjordseed-longpress-link'));
  window.document.querySelector('#rss').remove();
  await delay(180);
  assert.equal(window.document.querySelector('fjordseed-safari-panel'), null);
});
