/* Interactive SVG actors behind the UI, like the original mountain goats. */
(() => {
 'use strict';
 if(!document.querySelector('.ambient-scene'))return;
 const root=document.documentElement,reduced=matchMedia('(prefers-reduced-motion: reduce)');
 const layer=document.createElement('div');layer.className='viking-battle';layer.setAttribute('role','group');layer.setAttribute('aria-label','Vikingekamp i baggrunden. Klik på en kriger for at slå med øksen.');
 document.body.append(layer);
 const battle=new window.FjordBattleModel(innerWidth<700?16:24);
 let raf=0,last=0,renderedRound=0,actors=[],boats=[],splashes=new Map();
 const axe='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 65 85"><path d="M17 80L42 9" stroke="#211d17" stroke-width="9"/><path d="M17 80L42 9" stroke="#b69a69" stroke-width="5"/><path d="M37 13L53 5Q49 18 62 31L41 30L35 25Z" fill="#b9c9c5" stroke="#445959" stroke-width="2"/><path d="M53 5Q49 18 62 31" stroke="#edf0d9" stroke-width="3"/></svg>';
 layer.style.setProperty('--axe-cursor',`url("data:image/svg+xml,${encodeURIComponent(axe)}") 18 20, crosshair`);
 function art(u){
  const cloth=u.team?'#507c84':'#964f43',edge=u.team?'#9fc3c1':'#d5a07c';
  const beard=['#c4a16c','#77503b','#d0b68c','#51443b'][u.id%4];
  return `<svg viewBox="0 0 90 110" aria-hidden="true"><ellipse cx="42" cy="103" rx="29" ry="4" fill="#061115" opacity=".3"/><g class="viking-leg-left" stroke="#302e29" stroke-width="9" stroke-linecap="round"><path d="M33 68L30 94l-6 5"/></g><g class="viking-leg-right" stroke="#39352d" stroke-width="9" stroke-linecap="round"><path d="M46 68L50 94l6 5"/></g><g class="viking-body" stroke="#263237" stroke-width="1.7" stroke-linejoin="round"><path d="M23 39Q13 52 13 81L36 76 60 85 57 46Z" fill="${cloth}"/><path d="M29 38L48 37 56 70 26 73Z" fill="#68706a"/><path d="M28 47h24M27 53h27M27 59h28" stroke="#a5aaa0" stroke-dasharray="2 3" opacity=".5"/><path d="M24 66L56 63 58 76 25 78Z" fill="${cloth}"/><path d="M26 64l29-3" stroke="#ad8b58" stroke-width="4"/><path d="M23 41l-6 15 13 9" stroke="#baa07b" stroke-width="8" fill="none"/><path d="M27 20Q39 9 50 24L47 42 35 47 25 34Z" fill="#d1b08b"/><path d="M27 31L34 36 47 32 46 49 37 57 28 44Z" fill="${beard}"/><path d="M34 28h3m7 0h3" stroke="#1a2629" stroke-width="2.4"/><path d="M23 25Q22 7 37 6Q53 7 52 25L41 22 40 34 36 34 34 22Z" fill="#86978f"/><path d="M37 6v16M24 22h27" stroke="#ceccae" stroke-width="2"/><g class="viking-weapon"><path d="M47 44L58 53 69 38" fill="none" stroke="#bca080" stroke-width="8" stroke-linecap="round"/><path d="M62 58L76 9" stroke="#2a2e2b" stroke-width="7"/><path d="M62 58L76 9" stroke="#ad8759" stroke-width="4"/><path d="M72 14L84 8Q80 18 89 27L74 26 69 23Z" fill="#aebdb3"/><path d="M84 8Q80 18 89 27" stroke="#dddcc5" stroke-width="2"/></g><g><circle cx="23" cy="59" r="21" fill="${cloth}" stroke="#c4b28b" stroke-width="3"/><path d="M23 39v40M3 59h40" stroke="${edge}" stroke-width="7" opacity=".6"/><circle cx="23" cy="59" r="7" fill="#7e8d85" stroke="#d2c6a5" stroke-width="2"/><path d="M9 45l3 3M34 45l-3 3M8 73l4-4M36 73l-4-4" stroke="#e1cfa4"/></g></g><path class="viking-spark" d="M77 36l5-8m-3 11 10-2m-11 6 8 5" stroke="#f5d79b" stroke-width="2"/></svg>`;
 }
 function build(){
  layer.replaceChildren();splashes.clear();renderedRound=battle.round;
  boats=battle.boats.map(b=>{
   const el=document.createElement('div');el.className='viking-longship';el.setAttribute('aria-hidden','true');
   const cloth=b.team?'#688e91':'#a66b55';
   el.innerHTML=`<svg viewBox="0 0 240 160"><ellipse class="ship-wake" cx="120" cy="146" rx="106" ry="9" fill="none" stroke="#afc9bb" stroke-width="2" opacity=".3"/><path d="M118 118V12" stroke="#8e714c" stroke-width="6"/><path d="M119 17Q166 26 190 88L121 79Z" fill="${cloth}" stroke="#d6c5a0" stroke-width="2"/><path d="M135 24l8 57m15-47 9 51" stroke="#d8cfb1" stroke-width="12" opacity=".6"/><path d="M21 111Q7 95 13 78L26 72 34 80 22 84 28 107M215 109Q230 85 221 77" fill="none" stroke="#9c784a" stroke-width="9"/><path d="M19 107Q119 127 222 106L203 133Q120 159 40 133Z" fill="#624b34" stroke="#ba955d" stroke-width="3"/><path d="M35 121Q120 143 208 120" fill="none" stroke="#b19163" stroke-width="2"/><g class="ship-oars" stroke="#c2a77b" stroke-width="4"><path d="M61 117l-27 26m61-22-22 26m58-25-16 26m52-28-9 25m39-30-2 22"/></g>${[58,87,116,145,174].map((x,i)=>`<circle cx="${x}" cy="119" r="12" fill="${i%2?'#b29a69':cloth}" stroke="#d1b98c" stroke-width="2"/><circle cx="${x}" cy="119" r="3" fill="#9aaba2"/>`).join('')}</svg>`;
   layer.append(el);return el;
  });
  actors=battle.units.map(u=>{
   const el=document.createElement('button');el.type='button';el.className='viking-warrior';el.innerHTML=art(u);
   el.setAttribute('aria-label',`${u.team?'Blå':'Rød'} viking ${u.id+1}: slå med øksen`);
   el.style.setProperty('--swing-delay',`${-(u.id%5)*.23}s`);
   el.addEventListener('click',()=>{
    if(root.dataset.theme!=='viking'||document.querySelector('dialog[open]')||!battle.kill(u.id))return;
    if(!reduced.matches){const effect=document.createElement('div');effect.className='viking-player-axe';effect.innerHTML=axe;effect.setAttribute('aria-hidden','true');effect.style.left=`${u.x*innerWidth+12}px`;effect.style.top=`${u.y*innerHeight-69}px`;layer.append(effect);setTimeout(()=>effect.remove(),500);}
    render();
   });
   el.weapon=el.querySelector('.viking-weapon');el.body=el.querySelector('.viking-body');
   layer.append(el);return el;
  });
 }
 function render(){
  if(renderedRound!==battle.round)build();
  layer.dataset.phase=battle.phase;layer.dataset.round=String(battle.round);
  const motion=root.dataset.animation!=='false'&&!reduced.matches;
  battle.boats.forEach((b,i)=>{
   const el=boats[i],scale=innerWidth<700?.65:.9;
   el.hidden=battle.time>26;
   el.style.zIndex=String(Math.round(b.y*1000)+1);
   el.style.transform=`translate(${b.x*innerWidth-120}px,${b.y*innerHeight-136+(motion?Math.sin(battle.time*2+b.team)*2:0)}px) scale(${scale})`;
  });
  battle.units.forEach((u,i)=>{
   const el=actors[i],dead=u.deadAt!==null,age=dead?battle.time-u.deadAt:0;
   const scale=(innerWidth<700?.7:.86)+(u.y-.7)*.65;
   const jumpAge=battle.time-u.jumpAt,jump=motion&&jumpAge>=0&&jumpAge<.65?Math.sin(jumpAge/.65*Math.PI)*u.jumpHeight:0;
   const attackAge=battle.time-u.attackAt;
   const impact=u.impactDelay,windup=impact*.72,duration=u.attackDuration;
   const pose=u.attackStyle==='sweep'?{back:-35,hit:78}:u.attackStyle==='jab'?{back:20,hit:-12}:{back:-85,hit:48};
   const swing=attackAge<windup?8+(pose.back-8)*attackAge/windup:attackAge<impact?pose.back+(pose.hit-pose.back)*(attackAge-windup)/(impact-windup):attackAge<duration?pose.hit+(8-pose.hit)*(attackAge-impact)/(duration-impact):8;
   const lunge=attackAge>=0&&attackAge<duration?Math.sin(Math.min(1,attackAge/impact)*Math.PI/2)*Math.max(0,1-Math.max(0,attackAge-impact)/(duration-impact)):0;
   el.weapon.style.transform=`translateX(${!dead&&u.attackStyle==='jab'?lunge*13:0}px) rotate(${dead?30:swing}deg)`;
   el.body.style.transform=`translateX(${dead?0:lunge*3}px) rotate(${!dead&&battle.time-u.hitAt<.22?-10:dead?0:lunge*(u.attackStyle==='sweep'?9:4)}deg)`;
   el.style.zIndex=String(Math.round(u.y*1000));
   el.style.transform=`translate(${u.x*innerWidth-38}px,${u.y*innerHeight-90-jump}px) scale(${scale}) rotate(${dead?(motion?Math.min(1,age/.45):1)*u.facing*85:0}deg)`;
   el.style.opacity=dead?String(motion?Math.max(0,1-Math.max(0,age-1.8)/2):0):'1';
   el.style.setProperty('--facing',u.facing);
   el.classList.toggle('is-fallen',dead);el.classList.toggle('is-running',!dead&&u.state==='running');el.classList.toggle('is-fighting',!dead&&u.state==='fighting');
   el.disabled=dead;el.tabIndex=dead||u.x<0||u.x>1?-1:0;
   el.hidden=dead&&(!motion||age>4)||u.state==='offscreen';
  });
  const active=new Set();
  if(motion)for(const effect of battle.effects){
   active.add(effect.id);let el=splashes.get(effect.id);
   if(!el){
    el=document.createElement('div');el.className='viking-blood';el.setAttribute('aria-hidden','true');
    el.innerHTML='<i></i>'.repeat(7);layer.append(el);splashes.set(effect.id,el);
   }
   const age=battle.time-effect.at;
   el.style.transform=`translate(${effect.x*innerWidth}px,${effect.y*innerHeight-42}px)`;
   el.style.zIndex=String(Math.round(effect.y*1000)+2);
   el.style.opacity=String(Math.max(0,1-age/1.15));
   [...el.children].forEach((drop,j)=>{
    const vx=effect.direction*(12+j*6+effect.seed*10),vy=-35-j*9;
    drop.style.transform=`translate(${vx*age}px,${vy*age+95*age*age}px) rotate(${j*39}deg)`;
   });
  }
  for(const [id,el] of splashes)if(!active.has(id)){el.remove();splashes.delete(id);}
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
  const run=allowed();layer.classList.toggle('is-paused',!run);
  if(!run){cancelAnimationFrame(raf);raf=0;last=0;}
  // Still artwork is visible when animation is disabled from the beginning.
  if(active&&!run&&battle.time===0&&(reduced.matches||root.dataset.animation==='false')){for(let i=0;i<150;i++)battle.advance(.1,innerWidth,innerHeight);render();}
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
