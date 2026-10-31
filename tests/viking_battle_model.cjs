const assert=require('node:assert/strict');
const Battle=require('../static/viking-battle-model.js');
// Raiders leave their boats toward residents, without staging on the right.
for(const width of [390,1440]){
 const b=new Battle(2,()=>.5,true),resident=b.units[0],raider=b.units[1];
 resident.x=resident.targetX=.08;resident.y=resident.targetY=.80;
 resident.fleeDelay=100;raider.archer=false;
 const landAt=b.boats[raider.boat].landAt;
 while(b.time<landAt+1.15)b.advance(.05,width,950);
 const startX=raider.x,startY=raider.y;
 while(b.time<landAt+3){
  const previousX=raider.x;b.advance(.05,width,950);
  assert(raider.x<=previousX+1e-9,'Land straight toward the village without running right first');
 }
 assert(raider.x<startX&&raider.y>startY);
 assert.equal(raider.enemyId,resident.id);
 assert.equal(b.phase,'arrival','Pursuit begins before the last boat arrives');
}
for(const width of [390,1440]){
 let seed=71;
 const b=new Battle(width<700?40:64,()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;},true);
 assert.equal(b.units.filter(u=>u.team===1).length,width<700?9:12);
 assert.equal(b.units.filter(u=>u.civilian).length,width<700?20:32);
 const assertHouseSignals=()=>{
  for(const u of b.units.filter(u=>u.team===1&&u.state==='inside')){
   const house=b.settlement[u.visitingHouse??u.raidHouse];
   assert(['hearts','skulls'].includes(house.symbolType)&&house.symbolUntil>b.time,'Every house entry must show a symbol throughout the visit');
  }
 };
 let hiding=false,visiting=false;const symbols=new Set();
 while(b.time<150&&b.phase!=='raid'){
  b.advance(.05,width,950);
  assertHouseSignals();
  hiding ||= b.units.some(u=>u.civilian&&u.state==='hiding');
  visiting ||= b.units.some(u=>u.visitingHouse!=null&&u.state==='inside');
  b.settlement.forEach(h=>{if(h.symbolType)symbols.add(h.symbolType);});
  for(const u of b.units.filter(u=>u.civilian&&u.capturedBy==null)){
   assert(u.x>=.025&&u.x<=.64&&u.y>=Battle.LAND&&u.y<=.95,'Frightened residents stay in the picture');
   assert.notEqual(u.state,'offscreen');
  }
 }
 const residents=b.units.filter(u=>u.civilian);
 assert.equal(b.phase,'raid');
 assert(residents.some(u=>u.deadAt!==null),'Raiders can catch and kill fleeing residents');
 assert(residents.some(u=>u.sheltered&&u.deadAt===null),'Hearts spare residents inside houses');
 assert(residents.some(u=>u.diedInside),'Skulls resolve a fatal house encounter');
 assert(hiding&&visiting);assert.deepEqual([...symbols].sort(),['hearts','skulls']);
 assert(residents.every(u=>u.deadAt!==null||u.sheltered||u.capturedBy!=null));
 assert.equal(b.boats.length,3);
 const captives=residents.filter(u=>u.capturedBy!=null);assert(captives.length>0&&captives.length<=3);
 assert(residents.every(u=>u.attackAt===-10),'Residents flee without fighting');
 const fallen=residents.find(u=>u.deadAt!==null),position=[fallen.x,fallen.y];
 b.advance(.1,width,950);assert.deepEqual([fallen.x,fallen.y],position);
 let earlyReturn=false,lootReturn=false;
 while(b.time<b.exitStart-.1){
  const previous=b.units.map(u=>({x:u.x,y:u.y,state:u.state}));b.advance(.05,width,950);assertHouseSignals();
  for(const u of b.units.filter(u=>u.team===1&&u.deadAt===null&&!u.withdrawing)){
   earlyReturn ||= u.returnAt!==undefined;
   lootReturn ||= u.loot&&u.returnAt!==undefined;
   if(u.state==='running'&&previous[u.id].state==='running'&&u.returnAt!==b.time)assert(Math.hypot(u.x-previous[u.id].x,u.y-previous[u.id].y)>0,'Finished raiders must not run in place');
   if(!['landing','boarding'].includes(u.state))assert(b.time-u.jumpAt>.65,'No idle or random jumps after combat');
  }
 }
 assert(earlyReturn&&lootReturn,'Finished raiders immediately carry their loot back to the boats');
 const crew=b.units.filter(u=>u.team===1&&u.deadAt===null&&!u.withdrawing),round=b.round;
 assert(crew.some(u=>u.loot),'Raiders carry loot bags back');
 let jumping=false;
 while(b.sailStart===null){
  b.advance(.05,width,950);
  assert.equal(b.round,round,'Do not restart before everyone has boarded');
  assert(b.time<b.exitStart+25,'All surviving raiders must reach their boats');
  jumping ||= crew.some(u=>u.state==='boarding');
  for(const boat of b.boats)assert.equal(boat.y,boat.dockY,'Ships wait at the shore for their crew');
  for(const u of crew)if(u.state==='running')assert(u.y>=Battle.LAND,'Returning raiders run on land');
 }
 assert(jumping);assert(crew.every(u=>u.state==='aboard'));
 assert.equal(b.phase,'departure');
 for(let i=0;i<160;i++){
  const previous=b.boats.map(boat=>({y:boat.y,scale:boat.scale}));b.advance(.05,width,950);
  b.boats.forEach((boat,i)=>{assert(boat.y<=previous[i].y);assert(boat.scale<=previous[i].scale);});
  for(const u of crew){const boat=b.boats[u.boat];assert(Math.abs(u.x-boat.x-u.seatOffset*boat.scale/width)<1e-9);assert(u.y<Battle.LAND);}
 }
 assert(b.boats.every(boat=>boat.y<boat.dockY&&boat.scale<.63));
 assert(captives.every(u=>u.state==='aboard'&&u.deadAt===null),'Captured residents leave alive with their escort');
 while(b.phase!=='clear')b.advance(.05,width,950);
 assert(b.boats.every(boat=>!boat.visible));
 while(b.round===round)b.advance(.05,width,950);
 assert.equal(b.returnStart,null);assert.equal(b.sailStart,null);assert.equal(b.departureEnd,null);
 b.reset();assert(b.units.every(u=>u.deadAt===null&&u.enemyId===null&&!u.sheltered&&u.visitingHouse==null&&u.capturedBy==null&&u.captiveId==null));
 assert(b.settlement.every(h=>!h.encounter&&!h.symbolType));
}
{
 let seed=95;const b=new Battle(16,()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;},true);
 b.units.filter(u=>u.team===1).forEach(u=>{u.deadAt=0;});b.checkVictory=()=>{};
 b.time=b.arrivalEnd;const directions=new Map();
 for(let i=0;i<400;i++){
  const xs=b.units.map(u=>u.x);b.advance(.05,1440,950);
  for(const u of b.units.filter(u=>u.civilian&&!u.seekShelter)){
   if(!directions.has(u.id))directions.set(u.id,new Set());
   if(Math.abs(u.x-xs[u.id])>.00001)directions.get(u.id).add(Math.sign(u.x-xs[u.id]));
  }
 }
 assert([...directions.values()].some(d=>d.has(-1)&&d.has(1)),'Panicked residents change direction');
}
console.log('PASS direct pursuit, bounded panic, hiding, both house outcomes and clean restart on mobile/desktop');
{
 const b=new Battle(4,()=>.5,true);b.time=b.arrivalEnd+1;
 const captive=b.units[0],escort=b.units[1];captive.state='running';
 assert(b.capture(escort,captive));assert(!b.capture(b.units[3],captive),'A resident cannot have two escorts');
 assert.equal(captive.capturedBy,escort.id);
 b.kill(escort.id);assert.equal(captive.capturedBy,null);assert.equal(escort.captiveId,null);
 assert.equal(captive.state,'running','Prisoners can escape if their escort is defeated on shore');
 assert.equal(b.winner,null,'A freed resident still counts as a survivor');
}
for(const occupied of [false,true]){
 const b=new Battle(4,()=>.5,true);b.time=b.arrivalEnd+1;
 for(const resident of b.units.filter(u=>u.civilian)){resident.houseId=occupied?1:2;resident.state='hiding';resident.sheltered=true;}
 b.checkVictory();
 const raider=b.units[1];raider.raidHouse=1;raider.raidDuration=1;raider.raidDelay=0;raider.raidFromX=raider.x;raider.raidFromY=raider.y;
 b.advance(1.1);
 assert.equal(raider.state,'inside');assert.equal(b.settlement[1].symbolType,'hearts');
 assert(b.settlement[1].symbolUntil>b.time,'Both empty and occupied houses show symbols during post-battle looting');
}
{
 const b=new Battle(4,()=>.5,true),resident=b.units[0];
 resident.houseId=1;resident.state='hiding';resident.x=b.settlement[1].x;resident.y=b.settlement[1].y;
 const hp=resident.hp;
 b.arrows.push({id:1,target:resident.id,tx:resident.x,ty:resident.y,at:0,duration:.45,direction:-1});
 b.advance(.5);assert.equal(resident.hp,hp,'Residents inside houses cannot be hit by arrows outside');
}
for(const count of [16,24,40,64]){
 let seed=71;
 const b=new Battle(count,()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;});
 assert(b.units.filter(u=>u.team===0).every(u=>u.y>=Battle.LAND));
 assert(b.units.filter(u=>u.team===1).every(u=>u.boat!==null));
 for(let i=0;i<Math.ceil(b.arrivalEnd*10);i++)b.advance(.1);
 assert(b.units.every(u=>u.x>0&&u.x<1));
 assert(b.kill(0));assert(!b.kill(0));
 // Exercise the five-minute fallback separately from early victory.
 b.kill(1);b.wound=()=>{};
 while(b.time<270)b.advance(.1);
 assert.equal(b.round,1);
 assert(b.units.some(u=>u.deadAt===null));
 assert(b.units.filter(u=>u.deadAt!==null).length>1);
 for(let i=0;i<270;i++)b.advance(.1);
 assert.equal(b.phase,'clear');
 assert(b.units.every(u=>u.x<0||u.x>1));
 for(let i=0;i<31;i++)b.advance(.1);
 assert.equal(b.round,2);
 assert(b.units.every(u=>u.deadAt===null));
 assert(b.units.filter(u=>u.team===0).every(u=>u.y>=Battle.LAND));
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
   if(!['sailing','landing'].includes(u.state))assert(u.y>=Battle.LAND,'Walking and combat must stay on dry land');
   if(u.state==='fighting'&&u.deadAt===null){
    if(u.attackAt>0){
     styles.add(u.attackStyle);
     assert(u.attackDuration<=.64&&u.nextAttack-u.attackAt<=1.15,'Melee swings and recovery must keep the faster pace');
    }
    const enemy=b.units[u.enemyId];
    assert(Math.abs(u.x-enemy.x)*width<(u.spearman?77:39),'Weapon swings must happen within contact range');
    assert(Math.abs(u.y-enemy.y)*950<16,'Opponents must share a ground plane');
    contact=true;
   }
  }
  assert(b.effects.length<=40,'Effect storage must remain bounded');
 }
 assert(sailing&&jumping&&contact&&blood&&arrows);
 assert(twoAgainstOne,'Some close-range fights should have two attackers against one');
 assert.deepEqual([...styles].sort(),['jab','overhead','spear-low','spear-thrust','sweep']);
 if(b.phase!=='clear')assert(b.boats.filter(boat=>b.time>=boat.delay).every(boat=>boat.visible));
 b.reset();assert.notDeepEqual(b.units.map(u=>u.targetX),initialTargets);
 assert.equal(b.effects.length,0);
 assert.equal(b.arrows.length,0);
}
{
 const b=new Battle(4,()=>.5);
 b.time=b.arrivalEnd+5;
 for(const [i,u] of b.units.entries()){u.x=[.3,.35,.2,.9][i];u.y=.85;u.state='guarding';u.boat=null;u.archer=false;u.decisionAt=100;}
 b.units[0].enemyId=3;
 for(let i=0;i<100;i++){
  b.advance(.02,1000,1000);
  assert(b.units[0].x<b.units[1].x,'Approaching enemies must not walk through each other');
 }
 assert.equal(b.units[0].enemyId,1,'Engage the nearby enemy instead of chasing a distant assignment');
 const slow=b.units[2];slow.lostLeg=true;slow.x=.05;slow.y=.94;
 const old=slow.x;b.move(slow,100,0,.1,1000,1000,50);
 assert(slow.x-old<.003,'A lost leg must reduce movement speed');
 const victim=b.units[3];b.random=()=>.1;
 b.wound(victim,1,true);b.wound(victim,1,true);
 assert(victim.lostArm&&victim.lostLeg);
 assert(b.effects.some(e=>e.limb==='arm')&&b.effects.some(e=>e.limb==='leg'));
}
{
 const b=new Battle(16,()=>.5);
 let previous=.15;
 for(let i=0;i<70;i++){
  b.advance(.1);
  assert(b.boats[0].scale>=previous);previous=b.boats[0].scale;
  for(const boat of b.boats)assert(boat.y>=.35&&boat.y<=boat.dockY&&boat.y<Battle.LAND);
 }
}
console.log('PASS varied rounds, boat arrivals, jumps, close-range combat, blood and bounded effects on mobile/desktop');

for(const winner of [0,1]){
 const b=new Battle(8,()=>.5);
 for(let i=0;i<Math.ceil(b.arrivalEnd*10);i++)b.advance(.1);
 b.time=b.arrivalEnd+5;
 for(const u of b.units)if(u.team!==winner)b.kill(u.id);
 assert.equal(b.phase,winner===1?'raid':'retreat');assert.equal(b.winner,winner);
 assert.equal(b.units.filter(u=>u.flag).length,1);
 assert.equal(b.arrows.length,0);
 if(winner===1){
  let entered=false;
  while(b.time<b.exitStart){
   b.advance(.05);
   entered ||= b.units.some(u=>u.state==='inside');
   assert(b.units.filter(u=>u.state==='inside'||u.loot).every(u=>u.team===1));
   assert.equal(b.arrows.length,0);assert.equal(b.rocks.length,0);
  }
  assert(entered);assert(b.units.some(u=>u.loot));
 }
 const survivors=b.units.filter(u=>u.deadAt===null),ys=survivors.map(u=>u.y);
 for(let i=0;i<120;i++){
  const xs=survivors.map(u=>u.x);b.advance(.1);
  survivors.forEach((u,j)=>{assert(winner?u.x>=xs[j]:u.x<=xs[j]);assert.equal(u.y,ys[j]);assert.equal(u.enemyId,null);});
 }
 assert(survivors.every(u=>u.x<0||u.x>1));
 for(let i=0;i<12;i++)b.advance(.1);
 assert.equal(b.round,2);assert.equal(b.winner,null);assert.equal(b.exitStart,null);
 assert(b.units.every(u=>!u.flag&&!u.withdrawing&&!u.loot&&u.raidHouse===undefined));
}
{
 const b=new Battle(8,()=>.1);for(let i=0;i<Math.ceil(b.arrivalEnd*10);i++)b.advance(.1);b.time=b.arrivalEnd+5;
 const u=b.units[0],x=u.x;
 b.wound(u,1,true);assert(u.withdrawing);assert.equal(u.enemyId,null);
 b.advance(.1);assert(u.x<x);assert.notEqual(u.state,'fighting');
 // The last defender can actually die; no minimum-survivor health floor.
 for(const enemy of b.units.filter(e=>e.team===1)){
  enemy.hp=1;b.wound(enemy,1);
 }
 assert.equal(b.winner,0);assert.equal(b.phase,'retreat');
}
console.log('PASS victory flag, smooth outward movement, early restart, injury withdrawal and lethal final hits');

{
 let seed=891;const b=new Battle(64,()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;});
 assert(b.arrivalEnd>35);
 for(const formations of b.formations){assert.equal(formations.length,4);assert.equal(new Set(formations).size,3);}
 assert(b.catapults.filter(c=>c.team===1).every(c=>c.x>1));
 assert(b.catapults.filter(c=>c.team===0).every(c=>c.x>0&&c.x<1));
 let curved=false,stones=false,blueArrived=false;
 b.wound=()=>{};
 for(let i=0;i<(b.arrivalEnd+35)*20;i++){
  b.advance(.05,1440,950);
  for(const boat of b.boats){
   if(boat.id>=2&&b.boats[boat.id-2].progress<.9)assert(boat.progress<=Math.max(0,b.boats[boat.id-2].progress-.10)+1e-8);
   if(boat.progress>.2&&boat.progress<.8)curved ||= Math.abs(boat.x-(boat.entryX+(boat.dock-boat.entryX)*boat.progress))>.01;
   assert(boat.y>=.35&&boat.y<=boat.dockY);
  }
  stones ||= b.rocks.length>0;blueArrived ||= b.catapults.filter(c=>c.team===1).every(c=>c.x<1);
  assert(b.rocks.length<=12);
 }
 assert(curved&&stones&&blueArrived);
}
{
 const b=new Battle(16,()=>.1);for(let i=0;i<Math.ceil(b.arrivalEnd*10);i++)b.advance(.1);
 const u=b.units[0];u.hp=5;u.x=.45;
 b.wound(u,1,true);b.wound(u,1,true);assert(u.lostLeg&&u.withdrawing);
 b.wound=()=>{};
 for(let i=0;i<20;i++)b.advance(.1);
 assert(b.trails.length>=3);const mark={...b.trails[0]};
 const positions=new Set(b.trails.map(t=>t.x));assert(positions.size>1);
 for(let i=0;i<10;i++)b.advance(.1);
 assert.deepEqual(b.trails[0],mark,'Blood marks stay on the ground rather than following the unit');
 assert(b.trails.every(t=>t.y>=Battle.LAND));assert(b.trails.length<=240);
 b.reset();assert.equal(b.trails.length,0);assert.equal(b.rocks.length,0);
}
console.log('PASS staggered curved convoys, mixed squad formations, catapults and persistent withdrawal trails');

{
 const b=new Battle(8,()=>0);b.time=b.arrivalEnd+1;
 const axeVictim=b.units[1];axeVictim.hp=1;b.wound(axeVictim,1,true);
 assert(axeVictim.lostHead&&axeVictim.deadAt!==null);
 assert(b.effects.some(e=>e.limb==='head'&&e.unitId===axeVictim.id));
 const count=b.effects.length;b.wound(axeVictim,1,true);assert.equal(b.effects.length,count);
 const arrowVictim=b.units[3];arrowVictim.hp=1;b.wound(arrowVictim,1,false);
 assert(!arrowVictim.lostHead&&arrowVictim.deadAt!==null);
 const survivor=b.units[5];survivor.hp=4;b.wound(survivor,1,true);
 assert(!survivor.lostHead&&survivor.deadAt===null);
 b.reset();assert(b.units.every(u=>!u.lostHead));assert.equal(b.effects.length,0);
}
console.log('PASS occasional fatal axe decapitation, other weapons excluded, no repeated corpse hits and clean reset');
