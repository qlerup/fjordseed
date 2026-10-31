/* Interactive SVG actors behind the UI, like the original mountain goats. */
(() => {
 'use strict';
 if(!document.querySelector('.ambient-scene'))return;
 const root=document.documentElement,reduced=matchMedia('(prefers-reduced-motion: reduce)');
 const layer=document.createElement('div');layer.className='viking-battle';layer.setAttribute('role','group');layer.setAttribute('aria-label','Vikingekamp i baggrunden. Klik på en kriger for at slå med øksen.');
 document.body.append(layer);
 const fullButton=document.querySelector('#battle-full-view');
 const controls=document.createElement('div');controls.className='viking-view-controls';controls.hidden=true;
 controls.innerHTML='<button type="button" class="secondary">Tilbage til FjordSeed · Esc</button><span>Slaget ved fjorden</span>';
 document.body.append(controls);
 let hiddenPanels=[],previousFocus=null;
 function fullView(enabled){
  if(enabled){
   previousFocus=document.activeElement;
   hiddenPanels=[...document.body.children].filter(el=>el!==layer&&el!==controls&&!el.classList.contains('ambient-scene')).map(el=>[el,el.inert]);
   hiddenPanels.forEach(([el])=>el.inert=true);
  }else{hiddenPanels.forEach(([el,inert])=>el.inert=inert);hiddenPanels=[];}
  document.body.classList.toggle('viking-full-view',enabled);controls.hidden=!enabled;
  if(enabled)controls.querySelector('button').focus();else previousFocus?.focus();
 }
 fullButton?.addEventListener('click',()=>fullView(true));
 controls.querySelector('button').addEventListener('click',()=>fullView(false));
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!controls.hidden){event.preventDefault();fullView(false);}});
 const battle=new window.FjordBattleModel(innerWidth<700?40:64,Math.random,true);
 let raf=0,last=0,renderedRound=0,actors=[],boats=[],carts=[],houses=[],splashes=new Map(),arrows=new Map(),trails=new Map(),rocks=new Map();
 const axe='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 65 85"><path d="M17 80L42 9" stroke="#211d17" stroke-width="9"/><path d="M17 80L42 9" stroke="#b69a69" stroke-width="5"/><path d="M37 13L53 5Q49 18 62 31L41 30L35 25Z" fill="#b9c9c5" stroke="#445959" stroke-width="2"/><path d="M53 5Q49 18 62 31" stroke="#edf0d9" stroke-width="3"/></svg>';
 layer.style.setProperty('--axe-cursor',`url("data:image/svg+xml,${encodeURIComponent(axe)}") 18 20, crosshair`);
 function art(u){
  const cloth=u.team?'#507c84':'#827457',edge=u.team?'#9fc3c1':'#e2d3ad';
  const beard=['#c4a16c','#77503b','#d0b68c','#51443b'][u.id%4];
  return `<svg viewBox="0 0 90 110" aria-hidden="true"><ellipse cx="42" cy="103" rx="29" ry="4" fill="#061115" opacity=".3"/><g class="viking-leg-left" stroke="#302e29" stroke-width="9" stroke-linecap="round"><path d="M33 68L30 94l-6 5"/></g><g class="viking-leg-right" stroke="#39352d" stroke-width="9" stroke-linecap="round"><path d="M46 68L50 94l6 5"/></g><g class="viking-body" stroke="#263237" stroke-width="1.7" stroke-linejoin="round"><path d="M23 39Q13 52 13 81L36 76 60 85 57 46Z" fill="${cloth}"/><path d="M29 38L48 37 56 70 26 73Z" fill="#68706a"/><path d="M28 47h24M27 53h27M27 59h28" stroke="#a5aaa0" stroke-dasharray="2 3" opacity=".5"/><path d="M24 66L56 63 58 76 25 78Z" fill="${cloth}"/><path d="M26 64l29-3" stroke="#ad8b58" stroke-width="4"/><path d="M23 41l-6 15 13 9" stroke="#baa07b" stroke-width="8" fill="none"/><g class="viking-head"><path d="M27 20Q39 9 50 24L47 42 35 47 25 34Z" fill="#d1b08b"/><path d="M27 31L34 36 47 32 46 49 37 57 28 44Z" fill="${beard}"/><path d="M34 28h3m7 0h3" stroke="#1a2629" stroke-width="2.4"/><path d="M23 25Q22 7 37 6Q53 7 52 25L41 22 40 34 36 34 34 22Z" fill="#86978f"/><path d="M37 6v16M24 22h27" stroke="#ceccae" stroke-width="2"/></g><g class="viking-weapon"><path d="M47 44L58 53 69 38" fill="none" stroke="#bca080" stroke-width="8" stroke-linecap="round"/><path d="M62 58L76 9" stroke="#2a2e2b" stroke-width="7"/><path d="M62 58L76 9" stroke="#ad8759" stroke-width="4"/><path d="M72 14L84 8Q80 18 89 27L74 26 69 23Z" fill="#aebdb3"/><path d="M84 8Q80 18 89 27" stroke="#dddcc5" stroke-width="2"/></g><g><circle cx="23" cy="59" r="21" fill="${cloth}" stroke="#c4b28b" stroke-width="3"/><path d="M23 39v40M3 59h40" stroke="${edge}" stroke-width="7" opacity=".6"/><circle cx="23" cy="59" r="7" fill="#7e8d85" stroke="#d2c6a5" stroke-width="2"/><path d="M9 45l3 3M34 45l-3 3M8 73l4-4M36 73l-4-4" stroke="#e1cfa4"/></g></g><path class="viking-spark" d="M77 36l5-8m-3 11 10-2m-11 6 8 5" stroke="#f5d79b" stroke-width="2"/></svg>`;
 }
 function build(){
  layer.replaceChildren();splashes.clear();arrows.clear();trails.clear();rocks.clear();renderedRound=battle.round;
  if(battle.village){
   const fields=document.createElement('div');fields.className='village-fields';fields.setAttribute('aria-hidden','true');
   fields.innerHTML='<svg viewBox="0 0 1000 1000" preserveAspectRatio="none"><g fill="#55553c" stroke="#8a7950" stroke-width="3"><path d="M550 780L750 795 720 880 540 860Z"/><path d="M555 902L805 917 780 983 550 970Z"/></g><g stroke="#a69b63" stroke-width="3" opacity=".75">'+Array.from({length:9},(_,i)=>`<path d="M${565+i*19} 795l-10 64M${565+i*24} 918l-7 48"/>`).join('')+'</g><g stroke="#76694d" stroke-width="4"><path d="M545 877l193 20m-190-28v19m39-15v19m39-15v19m39-15v19m39-15v19m33-15v19"/></g></svg>';
   layer.append(fields);
  }
  houses=battle.settlement.map(house=>{
   const el=document.createElement('div');el.className='viking-settlement-house'+(house.church?' is-church':'');el.setAttribute('aria-hidden','true');el.dataset.variant=String(house.variant??0);
   el.innerHTML=`<svg viewBox="0 0 150 150"><ellipse cx="75" cy="142" rx="72" ry="7" fill="#0c171b" opacity=".3"/><path d="M18 75h114v65H18Z" fill="${house.church?'#b2af91':'#b99c73'}" stroke="#514b3e" stroke-width="3"/><path d="M8 77L75 26l67 51Z" fill="#65513e" stroke="#9b8260" stroke-width="3"/><path d="M20 72l55-39 54 39M26 68h99M41 57h69" fill="none" stroke="#aa8d64" stroke-width="2" opacity=".6"/><path d="M22 80v58m106-58v58M20 103h110" stroke="#67533b" stroke-width="5"/><path d="M60 140v-34q15-18 30 0v34Z" fill="#182326" stroke="#7e6444" stroke-width="4"/><path d="M33 88h14v18H33Zm70 0h14v18h-14Z" fill="#403e32" stroke="#d1bc90" stroke-width="2"/>${house.church?'<path d="M58 74V32h34v42" fill="#b6b196" stroke="#5e5e50" stroke-width="3"/><path d="M52 34L75 12l23 22Z" fill="#605347"/><path d="M75 0v19M67 7h16" stroke="#d9c99c" stroke-width="4"/><path d="M69 48q6-10 12 0v15H69Z" fill="#39433d"/>':'<path d="M108 50V26h12v34" fill="#766c56" stroke="#b2a17a" stroke-width="2"/>'}</svg>`;
   el.insertAdjacentHTML('beforeend','<div class="house-symbols house-hearts">'+Array.from({length:5},(_,i)=>`<svg style="--i:${i}" viewBox="0 0 32 32"><path d="M16 28 4 16C-5 5 10-2 16 8 22-2 37 5 28 16Z" fill="#ed91a7" stroke="#fff0d1" stroke-width="1.5"/></svg>`).join('')+'</div><div class="house-symbols house-skulls">'+Array.from({length:5},(_,i)=>`<svg style="--i:${i}" viewBox="0 0 32 32"><path d="M8 23C-3 7 8 2 16 2S35 7 24 23v6H8Z" fill="#e7dec1" stroke="#394749" stroke-width="2"/><path d="M8 12h6v7H8Zm10 0h6v7h-6ZM14 22l2-4 2 4m-6 3v5m8-5v5" fill="#394749" stroke="#394749" stroke-width="1.5"/></svg>`).join('')+'</div>');
   layer.append(el);return el;
  });
  boats=battle.boats.map(b=>{
   const el=document.createElement('div');el.className='viking-longship';el.setAttribute('aria-hidden','true');
   const cloth=b.team?'#688e91':'#a66b55';
   el.innerHTML=`<svg viewBox="0 0 240 160"><ellipse class="ship-wake" cx="120" cy="146" rx="106" ry="9" fill="none" stroke="#afc9bb" stroke-width="2" opacity=".3"/><path d="M118 118V12" stroke="#8e714c" stroke-width="6"/><path d="M119 17Q166 26 190 88L121 79Z" fill="${cloth}" stroke="#d6c5a0" stroke-width="2"/><path d="M135 24l8 57m15-47 9 51" stroke="#d8cfb1" stroke-width="12" opacity=".6"/><path d="M21 111Q7 95 13 78L26 72 34 80 22 84 28 107M215 109Q230 85 221 77" fill="none" stroke="#9c784a" stroke-width="9"/><path d="M19 107Q119 127 222 106L203 133Q120 159 40 133Z" fill="#624b34" stroke="#ba955d" stroke-width="3"/><path d="M35 121Q120 143 208 120" fill="none" stroke="#b19163" stroke-width="2"/><g class="ship-oars" stroke="#c2a77b" stroke-width="4"><path d="M61 117l-27 26m61-22-22 26m58-25-16 26m52-28-9 25m39-30-2 22"/></g>${[58,87,116,145,174].map((x,i)=>`<circle cx="${x}" cy="119" r="12" fill="${i%2?'#b29a69':cloth}" stroke="#d1b98c" stroke-width="2"/><circle cx="${x}" cy="119" r="3" fill="#9aaba2"/>`).join('')}</svg>`;
   layer.append(el);return el;
  });
  carts=battle.catapults.map(cart=>{
   const el=document.createElement('div');el.className='viking-catapult';el.setAttribute('aria-hidden','true');
   el.innerHTML=`<svg viewBox="0 0 140 110"><path d="M17 82h101L94 72H34Z" fill="#665038" stroke="#b69664" stroke-width="3"/><path d="M38 79L65 37 94 79M65 37v42" fill="none" stroke="#a98754" stroke-width="7"/><path d="M32 69h69" stroke="#c7aa71" stroke-width="4"/><g class="catapult-arm"><path d="M65 58L103 12" stroke="#c4a16b" stroke-width="7"/><path d="M92 9q15 14 23 2" stroke="#59452e" stroke-width="6" fill="none"/></g><circle cx="35" cy="87" r="16" fill="#423d30" stroke="#a58a59" stroke-width="4"/><circle cx="105" cy="87" r="16" fill="#423d30" stroke="#a58a59" stroke-width="4"/><path d="M35 73v28m-14-14h28m56-14v28m-14-14h28" stroke="#967a50" stroke-width="3"/><path d="M48 70h33v13H48Z" fill="${cart.team?'#507c84':'#964f43'}"/></svg>`;
   el.arm=el.querySelector('.catapult-arm');layer.append(el);return el;
  });
  actors=battle.units.map(u=>{
   const el=document.createElement('button');el.type='button';el.className='viking-warrior';el.innerHTML=art(u);
   el.setAttribute('aria-label',`${u.team?'Viking':'Bosættelsens forsvarer'} ${u.id+1}: slå med øksen`);
   el.style.setProperty('--swing-delay',`${-(u.id%5)*.23}s`);
   el.addEventListener('click',()=>{
    if(u.civilian||root.dataset.theme!=='viking'||document.querySelector('dialog[open]')||!battle.kill(u.id))return;
    if(!reduced.matches){const effect=document.createElement('div');effect.className='viking-player-axe';effect.innerHTML=axe;effect.setAttribute('aria-hidden','true');effect.style.left=`${u.x*innerWidth+12}px`;effect.style.top=`${u.y*innerHeight-69}px`;layer.append(effect);setTimeout(()=>effect.remove(),500);}
    render();
   });
   el.weapon=el.querySelector('.viking-weapon');el.body=el.querySelector('.viking-body');
   el.querySelector('svg').insertAdjacentHTML('beforeend',`<g class="viking-victory-flag"><path d="M15 68V-45" stroke="#b89760" stroke-width="3"/><path class="flag-cloth" d="M17-43Q34-48 54-39L48-22Q32-30 17-23Z" fill="${u.team?'#507c84':'#964f43'}" stroke="#e2c58b" stroke-width="2"/><path d="M25-36l9 8m0-11-9 14" stroke="#eed8aa" stroke-width="2"/></g>`);
   el.body.lastElementChild.classList.add('viking-shield');
   if(!u.team){
    el.classList.add('settlement-defender');
    el.querySelector('.viking-shield').innerHTML='<path d="M5 39Q23 33 41 39L38 63Q34 78 23 87Q12 78 8 63Z" fill="#8a7554" stroke="#ddcba2" stroke-width="3"/><path d="M23 42v33M13 53h20" stroke="#eee3c9" stroke-width="5"/>';
    el.weapon.innerHTML='<path d="M47 44L58 53 69 38" fill="none" stroke="#bca080" stroke-width="8" stroke-linecap="round"/><path d="M64 50L80 8 84 3 85 10 70 52Z" fill="#c3ceca" stroke="#5b6d69" stroke-width="1.5"/><path d="M61 44l14 5M63 49l-4 12" stroke="#c7a570" stroke-width="4"/>';
    const beard=el.querySelector('.viking-head path:nth-child(2)');beard.setAttribute('d','M27 31L34 36 47 32 45 42 37 46 29 40Z');
   }
   if(u.civilian){
    el.classList.add('village-resident');el.classList.toggle('is-woman',u.female);
    el.querySelector('.viking-shield').innerHTML='';el.weapon.innerHTML='';
    el.body.querySelectorAll(':scope > path').forEach(path=>path.remove());
    const cloth=['#92775e','#6c8470','#956b62','#78848c'][Math.floor(u.id/2)%4];
    el.body.insertAdjacentHTML('afterbegin',`<path d="${u.female?'M27 38L47 38 61 94 18 94Z':'M26 38L49 38 55 77 23 77Z'}" fill="${cloth}" stroke="#3b433c" stroke-width="2"/><path d="M25 43L18 64m31-21 9 22" stroke="#c5a584" stroke-width="7" stroke-linecap="round"/><path d="M25 64h29" stroke="#66513c" stroke-width="3"/>`);
    el.querySelector('.viking-head').innerHTML=`<path d="M25 22Q25 9 39 10Q53 10 51 25L47 39 35 43 26 34Z" fill="#cbaa85"/><path d="${u.female?'M24 27Q19 7 38 6Q58 8 53 33L48 43 47 20 28 20 27 42Z':'M24 25Q21 8 39 8Q55 9 52 25L45 20 29 20Z'}" fill="${u.female?'#d1c3a2':'#6e5946'}"/><path d="M31 27h3m9 0h3" stroke="#313d37" stroke-width="2"/>`;
    el.setAttribute('aria-label',u.female?'Beboer: kvinde':'Beboer: mand');
   }
   el.querySelector('svg').insertAdjacentHTML('beforeend','<g class="viking-loot"><path d="M52 60q17-7 23 10l-2 18q-13 8-25-2l-1-16Z" fill="#b59554" stroke="#51462d" stroke-width="2"/><path d="M50 65l21 1m-11-2-4-8 10 1-3 7" fill="none" stroke="#e0c48c" stroke-width="2"/></g>');
   if(u.spearman){
    el.classList.add('is-spearman');
    el.weapon.insertAdjacentHTML('afterend','<g class="viking-spear"><path d="M44 47L60 52" stroke="#c4a17b" stroke-width="7" stroke-linecap="round"/><path d="M27 51L113 45" stroke="#bda16c" stroke-width="3"/><path d="M111 41L127 44 112 49Z" fill="#c3d0ca" stroke="#536b6b"/></g>');
    el.spear=el.querySelector('.viking-spear');
   }
   if(u.archer){
    el.classList.add('is-archer');
    el.weapon.insertAdjacentHTML('afterend','<g class="viking-bow"><path d="M45 46L67 47" stroke="#c4a17b" stroke-width="7" stroke-linecap="round"/><path d="M65 20Q91 47 65 76" fill="none" stroke="#bd955e" stroke-width="4"/><path class="bow-string" d="M65 20L54 47 65 76" fill="none" stroke="#d9cdb1" stroke-width="1.2"/><path d="M50 47h36m-5-3 5 3-5 3" stroke="#c9c3a6" fill="none" stroke-width="1.5"/></g>');
   }
   layer.append(el);return el;
  });
 }
 function render(){
  if(renderedRound!==battle.round)build();
  layer.dataset.phase=battle.phase;layer.dataset.round=String(battle.round);
  const strategyNames={shieldwall:'Skjoldmur',wedge:'Kile',flank:'Flankeangreb'};
  controls.querySelector('span').textContent=battle.phase==='raid'?'Vikingerne plyndrer husene':battle.exitStart!==null?(battle.winner===null?'Begge hold trækker sig tilbage':battle.winner?'Vikingerne drager af sted med byttet':'Bosættelsen er forsvaret'):(battle.village?'Vikingelandgang ved landsbyen':`Vikingelandgang · ${battle.formations[0].length} grupper pr. side`);
  if(battle.phase==='boarding')controls.querySelector('span').textContent='Vikingerne bærer byttet tilbage til bådene';
  if(battle.phase==='departure')controls.querySelector('span').textContent='Vikingerne sejler væk med byttet';
  const motion=root.dataset.animation!=='false'&&!reduced.matches;
  battle.settlement.forEach((house,i)=>{
   const el=houses[i],scale=(innerWidth<700?.42:.85)*(house.variant===1?1.15:house.variant===2?.8:1);
   el.style.transform=`translate(${house.x*innerWidth}px,${house.y*innerHeight}px) scale(${scale}) translate(-75px,-140px)`;
   el.style.zIndex=String(Math.round(house.y*1000)-2);
   el.classList.toggle('is-being-raided',battle.units.some(u=>u.raidHouse===house.id&&u.state==='inside'));
   el.classList.toggle('is-raided',battle.units.some(u=>u.raidHouse===house.id&&u.loot));
   el.classList.toggle('has-hearts',house.symbolType==='hearts'&&battle.time<house.symbolUntil);
   el.classList.toggle('has-skulls',house.symbolType==='skulls'&&battle.time<house.symbolUntil);
   el.classList.toggle('has-hidden-residents',battle.units.some(u=>u.civilian&&u.deadAt===null&&u.houseId===house.id&&u.state==='hiding'));
  });
  battle.boats.forEach((b,i)=>{
   const el=boats[i],scale=b.scale*(innerWidth<700?.65:1);
   el.hidden=!b.visible;
   el.style.zIndex=String(Math.round(b.y*1000)+1);
   el.style.transform=`translate(${b.x*innerWidth}px,${b.y*innerHeight+(motion?Math.sin(battle.time*1.1+b.id)*scale:0)}px) scale(${scale}) rotate(${b.heading||0}deg) translate(-120px,-146px)`;
  });
  battle.units.forEach((u,i)=>{
   const el=actors[i],dead=u.deadAt!==null,age=dead?battle.time-u.deadAt:0;
   const boat=['sailing','aboard'].includes(u.state)?battle.boats[u.boat]:null;
   const scale=boat?boat.scale*(innerWidth<700?.65:1)*.95:(innerWidth<700?.7:.86)+(u.y-.7)*.65;
   const jumpDuration=['landing','boarding'].includes(u.state)?1.2:.65;
   const jumpAge=battle.time-u.jumpAt,jump=motion&&jumpAge>=0&&jumpAge<jumpDuration?Math.sin(jumpAge/jumpDuration*Math.PI)*u.jumpHeight:0;
   const attackAge=battle.time-u.attackAt;
   const impact=u.impactDelay,windup=impact*.72,duration=u.attackDuration;
   const pose=u.attackStyle==='sweep'?{back:-35,hit:78}:u.attackStyle==='jab'?{back:20,hit:-12}:{back:-85,hit:48};
   const swing=attackAge<windup?8+(pose.back-8)*attackAge/windup:attackAge<impact?pose.back+(pose.hit-pose.back)*(attackAge-windup)/(impact-windup):attackAge<duration?pose.hit+(8-pose.hit)*(attackAge-impact)/(duration-impact):8;
   const lunge=attackAge>=0&&attackAge<duration?Math.sin(Math.min(1,attackAge/impact)*Math.PI/2)*Math.max(0,1-Math.max(0,attackAge-impact)/(duration-impact)):0;
   el.weapon.style.transform=`translateX(${!dead&&u.attackStyle==='jab'?lunge*13:0}px) rotate(${dead?30:swing}deg)`;
   if(el.spear)el.spear.style.transform=`translateX(${dead?0:lunge*15}px) rotate(${u.attackStyle==='spear-low'?8:0}deg)`;
   el.classList.toggle('is-ranged',u.archer&&u.state!=='fighting');
   el.classList.toggle('lost-arm',!!u.lostArm);el.classList.toggle('lost-leg',!!u.lostLeg);
   el.classList.toggle('lost-head',!!u.lostHead);
   el.classList.toggle('is-crawling',!dead&&!!u.lostLeg);
   el.classList.toggle('has-victory-flag',!!u.flag);
   el.classList.toggle('has-loot',!!u.loot);
   el.classList.toggle('is-shooting',u.archer&&battle.time-u.shotAt<.25);
   el.body.style.transform=`translateX(${dead?0:lunge*3}px) rotate(${!dead&&battle.time-u.hitAt<.22?-10:dead?0:lunge*(u.attackStyle==='sweep'?9:4)}deg)`;
   el.style.zIndex=String(Math.round(u.y*1000));
   const crawling=!dead&&u.lostLeg,crawl=motion&&crawling?Math.sin(battle.time*4+u.id):0;
   el.style.transform=`translate(${u.x*innerWidth-38}px,${u.y*innerHeight-90-jump+(crawling?crawl:0)}px) scale(${scale}) rotate(${dead?(motion?Math.min(1,age/.45):1)*u.facing*85:crawling?u.facing*(78+crawl*3):0}deg)`;
   el.style.opacity=dead?String(motion?Math.max(0,1-Math.max(0,age-1.8)/2):0):'1';
   el.style.setProperty('--facing',u.facing);
   el.classList.toggle('is-fallen',dead);el.classList.toggle('is-running',!dead&&u.state==='running');el.classList.toggle('is-fighting',!dead&&u.state==='fighting');
   el.disabled=dead||u.civilian;el.tabIndex=dead||u.civilian||u.x<0||u.x>1?-1:0;
   el.hidden=dead&&(!motion||age>4)||u.state==='offscreen'||u.state==='inside'||u.state==='hiding'||u.diedInside||(boat&&!boat.visible);
  });
  battle.catapults.forEach((cart,i)=>{
   const el=carts[i],age=battle.time-cart.shotAt,scale=innerWidth<700?.65:.9;
   el.style.transform=`translate(${cart.x*innerWidth-70}px,${cart.y*innerHeight-93}px) scale(${scale})`;
   el.style.zIndex=String(Math.round(cart.y*1000));el.hidden=battle.phase==='clear';
   el.arm.style.transform=`rotate(${age<.3?-80*age/.3:age<1.5?-80*(1-(age-.3)/1.2):0}deg)`;
  });
  const flyingRocks=new Set();
  if(motion)for(const rock of battle.rocks){
   flyingRocks.add(rock.id);let el=rocks.get(rock.id);
   if(!el){el=document.createElement('div');el.className='viking-boulder';el.setAttribute('aria-hidden','true');layer.append(el);rocks.set(rock.id,el);}
   const p=Math.min(1,(battle.time-rock.at)/rock.duration);
   el.style.transform=`translate(${(rock.x+(rock.tx-rock.x)*p)*innerWidth}px,${(rock.y+(rock.ty-rock.y)*p)*innerHeight-45-Math.sin(p*Math.PI)*130}px) rotate(${p*350}deg)`;
   el.style.zIndex='1100';el.style.opacity=String(rock.landed?Math.max(0,1-(battle.time-rock.at-rock.duration)/.5):1);
  }
  for(const [id,el] of rocks)if(!flyingRocks.has(id)){el.remove();rocks.delete(id);}
  const ground=new Set();
  for(const mark of battle.trails){
   ground.add(mark.id);let el=trails.get(mark.id);
   if(!el){el=document.createElement('div');el.className='viking-blood-trail';el.setAttribute('aria-hidden','true');layer.append(el);trails.set(mark.id,el);}
   el.style.transform=`translate(${mark.x*innerWidth}px,${mark.y*innerHeight+2}px) rotate(${mark.seed*180}deg) scale(${.7+mark.seed*.8})`;
   el.style.opacity=String(Math.min(.85,Math.max(0,(18-(battle.time-mark.at))/5)));
   el.style.zIndex=String(Math.round(mark.y*1000)-1);
  }
  for(const [id,el] of trails)if(!ground.has(id)){el.remove();trails.delete(id);}
  const active=new Set();
  if(motion)for(const effect of battle.effects){
   active.add(effect.id);let el=splashes.get(effect.id);
   if(!el){
    el=document.createElement('div');el.className='viking-blood';el.setAttribute('aria-hidden','true');
    el.innerHTML='<i></i>'.repeat(18);
    if(effect.limb){
     const fragment=document.createElement('span');fragment.className='viking-limb '+effect.limb;
     if(effect.limb==='head'){
      const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','20 4 36 56');
      const head=actors[effect.unitId]?.querySelector('.viking-head');if(head)svg.append(head.cloneNode(true));fragment.append(svg);
     }
     el.append(fragment);
    }
    layer.append(el);splashes.set(effect.id,el);
   }
   const age=battle.time-effect.at;
   el.style.transform=`translate(${effect.x*innerWidth}px,${effect.y*innerHeight-42}px)`;
   el.style.zIndex=String(Math.round(effect.y*1000)+2);
   el.style.opacity=String(Math.min(1,Math.max(0,(4-age)/1.2)));
   [...el.querySelectorAll('i')].forEach((drop,j)=>{
    const scatter=Math.abs(Math.sin(j*41.7+effect.seed*97)),flight=Math.min(age,.8);
    const vx=effect.direction*(5+scatter*70),vy=-20-Math.abs(Math.cos(j*19.1+effect.seed*31))*90;
    const y=Math.min(36+scatter*9,vy*flight+150*age*age);
    drop.style.transform=`translate(${vx*flight}px,${y}px) rotate(${j*39}deg) scale(${age>.9?1.2:.7+scatter*.5},${age>.9?.45:1})`;
   });
   const fragment=el.querySelector('.viking-limb');
   if(fragment)fragment.style.transform=`translate(${effect.direction*Math.min(age,.7)*50}px,${Math.min(39,(effect.limb==='head'?-24:0)-60*age+150*age*age)}px) rotate(${Math.min(age,.7)*effect.direction*250}deg)`;
  }
  for(const [id,el] of splashes)if(!active.has(id)){el.remove();splashes.delete(id);}
  const flying=new Set();
  if(motion)for(const arrow of battle.arrows){
   flying.add(arrow.id);let el=arrows.get(arrow.id);
   if(!el){el=document.createElement('div');el.className='viking-arrow';el.setAttribute('aria-hidden','true');el.innerHTML='<svg viewBox="0 0 36 10"><path d="M2 5h30m-6-4 8 4-8 4M8 5 2 1m6 4-6 4" fill="none" stroke="#ddc79c" stroke-width="2"/></svg>';layer.append(el);arrows.set(arrow.id,el);}
   const age=battle.time-arrow.at,p=Math.min(1,age/arrow.duration),arc=36;
   const dx=(arrow.tx-arrow.x)*innerWidth,dy=(arrow.ty-arrow.y)*innerHeight;
   const angle=Math.atan2(dy-arc*Math.PI*Math.cos(p*Math.PI),dx)*180/Math.PI;
   el.style.transform=`translate(${arrow.x*innerWidth+dx*p-18}px,${arrow.y*innerHeight+dy*p-44-Math.sin(p*Math.PI)*arc}px) rotate(${angle}deg)`;
   el.style.zIndex=String(Math.round((arrow.y+(arrow.ty-arrow.y)*p)*1000)+3);
   el.style.opacity=String(arrow.landed?Math.max(0,1-(age-arrow.duration)/.4):1);
  }
  for(const [id,el] of arrows)if(!flying.has(id)){el.remove();arrows.delete(id);}
 }
 function allowed(){return root.dataset.theme==='viking'&&root.dataset.animation!=='false'&&!reduced.matches&&!document.hidden&&!document.querySelector('dialog[open]');}
 function frame(t){
  raf=0;if(!allowed()){sync();return;}
  if(!last)last=t;
  if(t-last>=1000/30){battle.advance(Math.min((t-last)/1000,.1),innerWidth,innerHeight);last=t;render();}
  raf=requestAnimationFrame(frame);
 }
 function sync(){
  const active=root.dataset.theme==='viking';layer.hidden=!active;layer.inert=!active;
  if(!active&&!controls.hidden)fullView(false);
  const run=allowed();layer.classList.toggle('is-paused',!run);
  if(!run){cancelAnimationFrame(raf);raf=0;last=0;}
  // Still artwork is visible when animation is disabled from the beginning.
  if(active&&!run&&battle.time===0&&(reduced.matches||root.dataset.animation==='false')){const steps=Math.ceil(battle.arrivalEnd*10);for(let i=0;i<steps;i++)battle.advance(.1,innerWidth,innerHeight);render();}
  if(run&&!raf){last=0;raf=requestAnimationFrame(frame);}
 }
 build();render();sync();
 document.addEventListener('fjordseed:appearance',sync);document.addEventListener('visibilitychange',sync);reduced.addEventListener('change',sync);
 new MutationObserver(sync).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open']});
 window.addEventListener('resize',()=>{render();sync();});
 // Transparent page gutters may hit <main> rather than the actor underneath.
 // Only pass those empty-area clicks through; application controls retain priority.
 document.addEventListener('click',event=>{
  if(root.dataset.theme!=='viking'||event.target.closest('button,a,input,select,textarea,dialog,aside,form,.connection,.torrent,.tracker-card,.insights,.stats,.settings-tabs')||document.querySelector('dialog[open]'))return;
  const hit=[...actors].sort((a,b)=>Number(b.style.zIndex)-Number(a.style.zIndex)||actors.indexOf(b)-actors.indexOf(a)).find(el=>{if(el.hidden||el.disabled)return false;const r=el.getBoundingClientRect();return event.clientX>=r.left&&event.clientX<=r.right&&event.clientY>=r.top&&event.clientY<=r.bottom;});
  hit?.click();
 });
})();
