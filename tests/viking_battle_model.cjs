const assert=require('node:assert/strict');
const Battle=require('../static/viking-battle-model.js');
for(const count of [16,24]){
 let seed=71;
 const b=new Battle(count,()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;});
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

for(const width of [390,1440]){
 let seed=84;
 const b=new Battle(24,()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;});
 let sailing=false,jumping=false,contact=false,blood=false,twoAgainstOne=false,arrows=false;
 const styles=new Set();
 const initialTargets=b.units.map(u=>u.targetX);
 for(let i=0;i<2400;i++){
  b.advance(.05,width,950);
  sailing ||= b.units.some(u=>u.state==='sailing');
  jumping ||= b.units.some(u=>b.time-u.jumpAt>=0&&b.time-u.jumpAt<.65);
  blood ||= b.effects.length>0;
  arrows ||= b.arrows.length>0;
  assert(b.arrows.length<=32);
  for(const arrow of b.arrows)assert(arrow.duration>=.45&&arrow.duration<=1.4);
  twoAgainstOne ||= b.units.some(target=>target.deadAt===null&&b.units.filter(u=>u.deadAt===null&&u.enemyId===target.id&&u.state==='fighting').length===2);
  for(const u of b.units){
   assert(Number.isFinite(u.x)&&Number.isFinite(u.y));
   if(u.state==='fighting'&&u.deadAt===null){
    if(u.attackAt>0)styles.add(u.attackStyle);
    const enemy=b.units[u.enemyId];
    assert(Math.abs(u.x-enemy.x)*width<39,'Axe swings must happen within contact range');
    assert(Math.abs(u.y-enemy.y)*950<16,'Opponents must share a ground plane');
    contact=true;
   }
  }
  assert(b.effects.length<=40,'Effect storage must remain bounded');
 }
 assert(sailing&&jumping&&contact&&blood&&arrows);
 assert(twoAgainstOne,'Some close-range fights should have two attackers against one');
 assert.deepEqual([...styles].sort(),['jab','overhead','sweep']);
 assert(b.boats.every(boat=>boat.x<0||boat.x>1));
 b.reset();assert.notDeepEqual(b.units.map(u=>u.targetX),initialTargets);
 assert.equal(b.effects.length,0);
 assert.equal(b.arrows.length,0);
}
console.log('PASS varied rounds, boat arrivals, jumps, close-range combat, blood and bounded effects on mobile/desktop');
