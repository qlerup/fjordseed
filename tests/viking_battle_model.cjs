const assert=require('node:assert/strict');
const Battle=require('../static/viking-battle-model.js');
for(const count of [16,24]){
 const b=new Battle(count);
 assert(b.units.every(u=>u.x<0||u.x>1));
 for(let i=0;i<150;i++)b.advance(.1);
 assert(b.units.every(u=>u.x>0&&u.x<1));
 assert(b.kill(0));assert(!b.kill(0));
 for(let i=0;i<2550;i++)b.advance(.1);
 assert.equal(b.round,1);
 assert(b.units.some(u=>u.deadAt===null));
 assert(b.units.filter(u=>u.deadAt!==null).length>1);
 for(let i=0;i<270;i++)b.advance(.1);
 assert.equal(b.phase,'clear');
 assert(b.units.every(u=>u.x<0||u.x>1));
 for(let i=0;i<31;i++)b.advance(.1);
 assert.equal(b.round,2);
 assert(b.units.every(u=>u.deadAt===null));
 assert(b.units.every(u=>u.x<0||u.x>1));
}
console.log('PASS arrival, combat, click defeat, survivors leave, empty frame and 300-second restart');
