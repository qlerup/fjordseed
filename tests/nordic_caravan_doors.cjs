/* Run with node tests/nordic_caravan_doors.cjs. No browser dependencies. */
const assert = require('node:assert/strict');
global.window = {};
require('../static/nordic-caravan.js');
const scene = new window.FjordNordicCaravan();
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-6, `${a} != ${b}`);
for (const width of [300, 390, 800, 1400]) {
 for (const direction of [0, 1]) {
  const at = progress => scene.position({direction, progress}, width, 430);
  for (const link of [0, 1]) {
   const route = scene.route(direction, link, width, 430);
   const start = at(link), end = at(link + 1 - 1e-9);
   near(start.x, route.a.x);
   near(start.y, route.a.y - 18 * scene.villageScale(width) * (link ? 1.08 : 1));
   near(end.x, route.b.x);
   near(end.y, route.b.y - 18 * scene.villageScale(width) * (link ? 1 : 1.08));
   near(start.scale, 0);
   assert.ok(at(link + .02).scale < at(link + .06).scale);
   near(at(link + .2).scale, 1);
   near(at(link + .8).scale, 1);
   assert.ok(at(link + .94).scale > at(link + .98).scale);
   for (const boundary of [.09, .91, 1]) {
    const before = at(link + boundary - 1e-8), after = at(link + boundary + 1e-8);
    assert.ok(Math.hypot(before.x - after.x, before.y - after.y) < .001);
    assert.ok(Math.abs(before.scale - after.scale) < .001);
   }
  }
  near(at(-.01).scale, 0);
  near(at(2.01).scale, 0);
  // Each follower reaches the door in its own time, and survives the leader's arrival.
  const party = {direction, progress: 2.02};
  near(scene.position(party, width, 430).scale, 0);
  assert.ok(scene.position(party, width, 430, -.085).scale > 0);
 }
}
scene.advance(0, [1, 1], true);
assert.equal(scene.parties.length, 2);
assert.ok(scene.parties.every(p => p.progress === 0));
const party = scene.parties[0];
party.progress = 2.01;
scene.advance(.01, [0, 0], true);
assert.ok(scene.parties.includes(party));
scene.advance(1, [0, 0], true);
assert.ok(!scene.parties.includes(party));
const serial = scene.serial.join();
scene.advance(.5, [0, 0], true);
assert.equal(scene.serial.join(), serial);
scene.advance(0, [0, 0], false);
assert.equal(scene.parties.length, 0);
for (let i = 0; i < 1500; i++) scene.advance(.1, [1, 1], true);
assert.ok(scene.parties.length < 20);
// Observe actual draw calls around every door, including shared cargo and captives.
scene.backdrop = () => {};
scene.ellipse = () => {};
scene.line = () => {};
scene.chest = (c, a, b, scale) => assert.ok(Number.isFinite(scale) && scale > 0);
let count = 0;
scene.person = (c, x, y, scale) => {
 assert.ok(Number.isFinite(x) && Number.isFinite(y) && scale > 0);
 assert.equal(c.globalAlpha, 1);
 count++;
};
const context = {globalAlpha: 1, drawImage() {}, save() {}, restore() {}, setLineDash() {}};
for (const cargo of ['gold', 'captive']) for (const id of [0, 1]) {
 for (let progress = 0; progress < 2.085; progress += .005) {
  scene.parties = [{direction: id, progress, id, cargo}];
  scene.draw(context, 390, 430, 1, true, [1, 1], false);
 }
}
assert.ok(count > 1000);
console.log('PASS door alignment, continuous growth/shrink, followers, cargo, no fade and traffic lifecycle at 300–1400px');
