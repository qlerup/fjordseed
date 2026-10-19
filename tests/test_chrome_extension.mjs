import test from 'node:test';
import assert from 'node:assert/strict';
import {torrentLink, rssLink, sourceLink, seedAddress, permissionOrigin, readTorrent, selectSeedTab, MAX_BYTES} from '../chrome-extension/common.mjs';

test('Sagmire uses the same link rules with an exact HTTPS host allowlist', () => {
  assert.equal(torrentLink('https://sagmire.org/torrents/download/42?key=test#fragment'), 'https://sagmire.org/torrents/download/42?key=test');
  assert.deepEqual(sourceLink('https://sagmire.org/rss/42?key=private'), {kind:'rss',url:'https://sagmire.org/rss/42?key=private'});
  for (const url of ['http://sagmire.org/torrents/download/42','https://sagmire.org.evil.test/torrents/download/42',
    'https://sagmire.org:444/torrents/download/42','https://user:password@sagmire.org/torrents/download/42',
    'https://sagmire.org/rss/edit/42']) assert.throws(() => sourceLink(url));
  assert.throws(() => seedAddress('https://sagmire.org'));
});

test('RSS addresses preserve private query parameters and are classified without fetching', () => {
  for (const path of ['/rss/1283.'+'a'.repeat(32), '/rss/42?passkey=fixture&freeleech=1', '/rss?token=fixture', '/torrents/rss/42?key=fixture', '/rss.xml?key=fixture']) {
    const url = 'https://nordicbytes.org'+path;
    assert.equal(rssLink(url+'#fragment'), url);
    assert.deepEqual(sourceLink(url), {kind:'rss', url});
  }
  assert.deepEqual(sourceLink('https://nordicbytes.org/torrents/download/42'),
    {kind:'torrent', url:'https://nordicbytes.org/torrents/download/42'});
  for (const url of ['http://nordicbytes.org/rss/42', 'https://nordicbytes.org.evil.test/rss/42',
    'https://user:pass@nordicbytes.org/rss/42', 'https://nordicbytes.org:444/rss/42',
    'https://nordicbytes.org/rss/edit/42', 'https://nordicbytes.org/rss/create',
    'https://nordicbytes.org/torrents/42', 'javascript:alert(1)',
    'https://nordicbytes.org/rss?key='+'a'.repeat(4096)]) assert.throws(() => sourceLink(url));
});

test('reuse only the configured FjordSeed origin and preserve pending tab preference', () => {
  const address = 'http://192.168.1.110:8099/';
  const tabs = [
    {id:1,url:'http://192.168.1.110:8097/',active:true},
    {id:2,url:address+'#trackers',active:false,lastAccessed:10},
    {id:3,url:address+'login',active:true},
    {id:4,url:address+'api/status',active:true},
    {id:5,url:address,pendingUrl:'https://example.org/',active:true},
  ];
  assert.equal(selectSeedTab(tabs,address).id,3);
  assert.equal(selectSeedTab(tabs,address,2).id,2);
  assert.equal(selectSeedTab([tabs[0],tabs[3],tabs[4]],address),undefined);
});

test('only HTTPS NordicBytes torrent download links are accepted', () => {
  assert.equal(torrentLink('https://nordicbytes.org/torrents/download/42?key=test#fragment'),
    'https://nordicbytes.org/torrents/download/42?key=test');
  for (const url of ['http://nordicbytes.org/torrents/download/42',
    'https://nordicbytes.org.evil.test/torrents/download/42',
    'https://nordicbytes.org/torrents/42', 'https://user@ nordicbytes.org/torrents/download/42',
    'https://user:pass@nordicbytes.org/torrents/download/42',
    'https://nordicbytes.org:444/torrents/download/42', 'file:///test.torrent']) {
    assert.throws(() => torrentLink(url));
  }
});

test('destination preserves exact port while permission uses host pattern', () => {
  assert.equal(seedAddress('http://192.168.1.110:8099'), 'http://192.168.1.110:8099/');
  assert.equal(permissionOrigin('http://192.168.1.110:8099/'), 'http://192.168.1.110/*');
  for (const url of ['javascript:alert(1)', 'https://seed.test/login', 'https://seed.test/?token=x',
    'https://admin:secret@seed.test/', 'https://nordicbytes.org']) assert.throws(() => seedAddress(url));
});

test('torrent response survives binary transfer', async () => {
  const data = new Uint8Array([100, 49, 58, 120, 49, 58, 255, 101]);
  assert.deepEqual(Buffer.from(await readTorrent(new Response(data)), 'base64'), Buffer.from(data));
});

test('login pages, errors, invalid data, and oversized metadata fail closed', async () => {
  for (const response of [new Response('<html>Login</html>', {headers: {'Content-Type': 'text/html'}}),
    new Response('error', {status: 403}), new Response('not a torrent'),
    new Response('d1:xe', {headers: {'Content-Length': String(MAX_BYTES + 1)}}),
    new Response(new Uint8Array(MAX_BYTES + 1))]) await assert.rejects(readTorrent(response));
});
