const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
(async () => {
 const browser = await chromium.launch({headless:true});
 for (const width of [1440,390]) {
  const page = await browser.newPage({viewport:{width,height:950}});
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.setContent('<html data-theme="viking"><body style="margin:0;background:#20383b"><div class="ambient-scene"></div></body></html>');
  await page.addStyleTag({content:fs.readFileSync(path.join(root,'static/viking.css'),'utf8')});
  await page.addScriptTag({path:path.join(root,'static/viking-battle-model.js')});
  await page.evaluate(() => {
   let seed=71;const Model=window.FjordBattleModel;
   window.FjordBattleModel=class extends Model {
    constructor(count){super(count,()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;},true);window.testBattle=this;}
   };
   window.requestAnimationFrame=()=>0;
   window.doorSamples={};
  });
  await page.addScriptTag({path:path.join(root,'static/viking-battle.js')});
  const captured=new Set();
  for(let batch=0;batch<180;batch++){
   const shots=await page.evaluate(() => {
    const shots=[];
    for(let i=0;i<10;i++){
     testBattle.advance(.1,innerWidth,innerHeight);dispatchEvent(new Event('resize'));
     for(const u of testBattle.units){
      const door=u.doorPassage;if(!door||u.deadAt!==null)continue;
      const el=document.querySelectorAll('.viking-warrior')[u.id];
      const p=(testBattle.time-door.at)/door.duration;
      const key=`${u.id}-${door.at}`,r=el.getBoundingClientRect();
      (doorSamples[key]??=[]).push({entering:door.entering,width:r.width,p,opacity:getComputedStyle(el).opacity,hidden:el.hidden,running:el.classList.contains('is-running'),house:u.raidHouse!=null?'raid':'visit'});
      if(p>.4&&p<.6)shots.push(door.entering?'entering':'leaving');
     }
    }
    return shots;
   });
   for(const shot of shots)if(!captured.has(shot)){
    captured.add(shot);await page.screenshot({path:path.join(root,`test-results/village-door-${shot}-${width}.png`)});
   }
   if(await page.evaluate(()=>testBattle.round>1))break;
  }
  const samples=await page.evaluate(()=>Object.values(doorSamples));
  assert(samples.some(s=>s.length>4&&s[0].entering),'Observed entry');
  assert(samples.some(s=>s.length>4&&!s[0].entering),'Observed exit');
  assert(samples.some(s=>s[0].house==='raid'),'Observed looting doorway');
  assert(samples.some(s=>s[0].house==='visit'),'Observed resident doorway');
  for(const passage of samples){
   for(const s of passage){assert.equal(s.opacity,'1');assert.equal(s.hidden,false);assert(s.running);}
   for(let i=1;i<passage.length;i++){
    const change=passage[i].width-passage[i-1].width;
    assert(passage[i].entering?change<0:change>0,'Perspective follows travel direction');
   }
  }
  assert.deepEqual(errors,[]);
  console.log(`PASS doorway entry/exit, perspective scaling, opaque walking, visits and raids at ${width}px`);
  await page.close();
 }
 await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
