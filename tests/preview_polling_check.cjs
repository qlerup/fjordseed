const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const code = source.slice(source.indexOf('async function loadPreviewBenefits()'), source.indexOf("$('#benefit-tracker').onchange"));
function setup(responses = []) {
  const timers = new Map(), delays = [], rendered = [];
  let serial = 0, calls = 0;
  const elements = {
    '#ratio-dialog': {open: true}, '#benefit-tracker': {value: ''},
    '#preview-benefits': {replaceChildren: data => rendered.push(data)},
  };
  const context = vm.createContext({
    $: id => elements[id], FormData, benefitView: data => data,
    renderRatioPreview() {},
    api: async () => { calls++; return responses.shift() || {status: 'pending'}; },
    setTimeout(fn, delay) { delays.push(delay); timers.set(++serial, fn); return serial; },
    clearTimeout: id => timers.delete(id),
  });
  vm.runInContext("let previewTimer,previewGeneration=0; const pendingTorrent=[['magnet','fixture']];" + code, context);
  return {context, timers, delays, rendered, calls: () => calls,
    async tick() { const [id, fn] = timers.entries().next().value; timers.delete(id); await fn(); }};
}

(async () => {
  const fast = setup([{status:'pending'}, {status:'matched', matches:[]}]);
  await fast.context.loadPreviewBenefits();
  assert.deepEqual(fast.delays, [500]);
  await fast.tick();
  assert.equal(fast.calls(), 2);
  assert.equal(fast.rendered.at(-1).status, 'matched');
  assert.equal(fast.timers.size, 0);

  const slow = setup();
  await slow.context.loadPreviewBenefits();
  for (let i = 0; i < 12; i++) await slow.tick();
  assert.deepEqual(slow.delays, [...Array(12).fill(500), 1500]);
  // Closing the dialog stops polling rather than starting another request.
  vm.runInContext("$('#ratio-dialog').open=false", slow.context);
  await slow.tick();
  assert.equal(slow.calls(), 13);
  assert.equal(slow.timers.size, 0);
  console.log('PASS fast preview polling, completed lookup, backoff and closed dialog');
})().catch(error => { console.error(error); process.exitCode = 1; });
