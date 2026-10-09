const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const elements = {};
const context = vm.createContext({
  $: id => elements[id] ||= {replaceChildren(...children) {this.children = children;}},
  card: torrent => torrent.name,
  size: String,
});
vm.runInContext(source.slice(source.indexOf('function renderDownloadLists('), source.indexOf('function renderFlow(')), context);
const torrents = [
  {name:'Old manual', added_on:100, created_at:900},
  {name:'New RSS', added_on:500, rss_feed:'Feed'},
  {name:'Latest manual', added_on:400, created_at:1},
  {name:'Old RSS', added_on:200, rss_feed:'Feed'},
  {name:'Unknown age'},
];
context.renderDownloadLists({torrents});
assert.deepEqual(elements['#torrent-list'].children, ['Latest manual','Old manual','Unknown age']);
assert.deepEqual(elements['#rss-torrent-list'].children, ['New RSS','Old RSS']);
assert.equal(torrents[0].name, 'Old manual');
console.log('PASS newest locally added torrents first in manual and RSS lists; tracker age ignored');
