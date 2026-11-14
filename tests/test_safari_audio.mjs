import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const {Window} = await import(process.env.FJORDSEED_TEST_HAPPY_DOM || 'happy-dom');
const source = fs.readFileSync(new URL('../safari-userscript/audio.js', import.meta.url), 'utf8');
function fixture(t, url = 'https://nordicbytes.org/torrents/42') {
  const window = new Window({url, settings: {enableJavaScriptEvaluation: true,
    disableCSSFileLoading: true, disableJavaScriptFileLoading: true,
    suppressInsecureJavaScriptEnvironmentWarning: true}});
  window.TextDecoder = TextDecoder;
  window.eval(source);
  t.after(() => window.happyDOM.close());
  return window;
}
// Structure from UNIT3D resources/views/torrent/partials/mediainfo.blade.php.
const summary = '<section class="mediainfo__audio"><h3>Audio</h3><dl>' +
  '<dt>1.</dt><dd><img alt="Danish">Danish / AC-3 / 6 channels / 640 kb/s / Dansk</dd>' +
  '<dt>2.</dt><dd>English / DTS XLL / 8 channels / 4 000 kb/s / Original</dd></dl></section>';
test('desktop summary retains separate tracks, languages and codecs as text', t => {
  const w = fixture(t);
  w.document.body.innerHTML = summary;
  assert.deepEqual([...w.fjordSeedAudioTracks(w.document)], [
    'Danish / AC-3 / 6 channels / 640 kb/s / Dansk',
    'English / DTS XLL / 8 channels / 4 000 kb/s / Original'
  ]);
});
test('raw MediaInfo reads only audio, preserves duplicate languages and commercial formats', t => {
  const w = fixture(t);
  const pre = w.document.createElement('pre');
  pre.textContent = `General\nFormat : Matroska\nVideo\nFormat : HEVC\nAudio #1\nFormat : MLP FBA\nCommercial name : Dolby TrueHD with Dolby Atmos\nChannel(s) : 8 channels\nLanguage : English\nAudio #2\nFormat : AC-3\nLanguage : English\nText #1\nLanguage : Danish\nFormat : PGS`;
  w.document.body.append(pre);
  assert.deepEqual([...w.fjordSeedAudioTracks(w.document)], [
    'English / Dolby TrueHD with Dolby Atmos / 8 channels', 'English / AC-3'
  ]);
});
test('mobile details fetch uses the selected ID, same-origin login, and no private download parameters', async t => {
  const w = fixture(t, 'https://nordicbytes.org/mobile/torrents/999');
  const requests = [];
  w.fetch = async (url, options) => {
    requests.push({url, options});
    return new Response(summary, {headers: {'Content-Type': 'text/html; charset=utf-8'}});
  };
  const tracks = await w.loadFjordSeedAudio('https://nordicbytes.org/torrents/download/42?key=private');
  assert.equal(tracks.length, 2);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, 'https://nordicbytes.org/torrents/42');
  assert.equal(requests[0].options.credentials, 'same-origin');
  assert.equal(requests[0].options.redirect, 'error');
});
test('existing summary is used only on the matching details page', async t => {
  const w = fixture(t);
  w.document.body.innerHTML = summary;
  w.fetch = () => { throw Error('must not fetch'); };
  assert.equal((await w.loadFjordSeedAudio('https://nordicbytes.org/torrents/download/42')).length, 2);
});
test('login, empty metadata and large pages have distinct outcomes', async t => {
  const w = fixture(t, 'https://nordicbytes.org/torrents');
  w.fetch = async () => new Response('<input type="password">', {headers: {'Content-Type': 'text/html'}});
  await assert.rejects(w.loadFjordSeedAudio('https://nordicbytes.org/torrents/download/42'), /Log ind/);
  w.fetch = async () => new Response('<h1>No MediaInfo</h1>', {headers: {'Content-Type': 'text/html'}});
  assert.equal((await w.loadFjordSeedAudio('https://nordicbytes.org/torrents/download/42')).length, 0);
  w.fetch = async () => new Response('x'.repeat(2 * 1024 * 1024 + 1), {headers: {'Content-Type': 'text/html'}});
  await assert.rejects(w.loadFjordSeedAudio('https://nordicbytes.org/torrents/download/42'), /for stor/);
});
test('unsupported links and other tracker origins never cause requests', async t => {
  const w = fixture(t);
  w.fetch = () => { throw Error('must not fetch'); };
  for (const url of ['https://sagmire.org/torrents/download/42',
    'https://nordicbytes.org.evil.test/torrents/download/42',
    'https://nordicbytes.org/torrents/delete/42', 'https://user@nordicbytes.org/torrents/download/42']) {
    await assert.rejects(w.loadFjordSeedAudio(url), /Vælg en torrent/);
  }
});

test('NordicBytes mobile fallback requests desktop metadata and restores mobile preference', async t => {
  const w = fixture(t, 'https://nordicbytes.org/torrents/42?mobile=1');
  Object.defineProperty(w.navigator, 'userAgent', {value: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0)'});
  const requests = [];
  w.fetch = async url => {
    requests.push(url);
    return new Response(url.endsWith('?desktop=1') ? summary : '<h1>Mobile detail page</h1>',
      {headers: {'Content-Type': 'text/html'}});
  };
  assert.equal((await w.loadFjordSeedAudio('https://nordicbytes.org/torrents/download/42')).length, 2);
  assert.deepEqual(requests, [
    'https://nordicbytes.org/torrents/42',
    'https://nordicbytes.org/torrents/42?desktop=1',
    'https://nordicbytes.org/torrents/42?mobile=1'
  ]);
});

test('desktop fetch failure still restores NordicBytes mobile preference', async t => {
  const w = fixture(t);
  Object.defineProperty(w.navigator, 'userAgent', {value: 'iPhone'});
  const requests = [];
  w.fetch = async url => {
    requests.push(url);
    if (url.endsWith('?desktop=1')) throw new w.TypeError('network failure');
    return new Response('<h1>Mobile detail page</h1>', {headers: {'Content-Type': 'text/html'}});
  };
  await assert.rejects(w.loadFjordSeedAudio('https://nordicbytes.org/torrents/download/42'), /kunne ikke hentes/);
  assert.equal(requests.at(-1), 'https://nordicbytes.org/torrents/42?mobile=1');
});

test('concurrent cards serialize persistent view switches', async t => {
  const w = fixture(t);
  Object.defineProperty(w.navigator, 'userAgent', {value: 'iPhone'});
  const switches = [];
  w.fetch = async url => {
    if (url.includes('?')) switches.push(new URL(url).search);
    if (url.endsWith('?desktop=1')) await new Promise(resolve => setTimeout(resolve, 10));
    return new Response(url.endsWith('?desktop=1') ? summary : '<h1>Mobile page</h1>',
      {headers: {'Content-Type': 'text/html'}});
  };
  const results = await Promise.all([42, 43].map(id =>
    w.loadFjordSeedAudio('https://nordicbytes.org/torrents/download/' + id)));
  assert(results.every(result => result.length === 2));
  assert.deepEqual(switches, ['?desktop=1', '?mobile=1', '?desktop=1', '?mobile=1']);
});
