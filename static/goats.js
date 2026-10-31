/* Fjord goats: local SVG artwork, bounded physics. */
(() => {
  'use strict';
  if (!document.querySelector('.ambient-scene')) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const layer = document.createElement('div');
  layer.className = 'goat-mountain';
  layer.setAttribute('aria-label', 'Bjerggeder – træk og slip for at kaste');
  document.body.append(layer);
  const palette = [['#eee8d7','#b8afa1'],['#aa7955','#654938'],['#44475a','#242735'],['#f7f5ef','#7d6358'],['#cab99d','#eee8db']];
  function art(index) {
    const [coat, patch] = palette[index % palette.length];
    return `<svg viewBox="0 0 100 80" aria-hidden="true"><g stroke="#292b38" stroke-width="2" stroke-linejoin="round"><g class="goat-legs"><path d="M29 48L25 70M40 49L43 70M61 48L58 70M69 47L73 69" fill="none" stroke="${patch}" stroke-width="6"/></g><path d="M20 36L12 26L14 41" fill="${coat}"/><ellipse cx="45" cy="43" rx="27" ry="17" fill="${coat}"/><ellipse cx="44" cy="40" rx="12" ry="10" fill="${patch}"/><g class="goat-face"><path d="M64 22Q49 4 60 3L68 20M75 20Q88 0 79 3L72 18" fill="#c9b89b"/><path d="M63 24L46 19L55 32M77 23L91 17L84 32" fill="${patch}"/><path d="M61 20Q73 13 81 25L80 43L72 53L60 43Z" fill="${coat}"/><path d="M67 49L72 62L77 48" fill="${patch}"/><ellipse cx="65" cy="32" rx="2" ry="3" fill="#131624"/><ellipse cx="76" cy="31" rx="2" ry="3" fill="#131624"/><path d="M68 40L74 40" stroke="#57443f"/><ellipse class="goat-mouth" cx="71" cy="46" rx="3" ry="2" fill="#57443f"/></g></g></svg>`;
  }
  // Match the cover-scaled mountain photo, including its mobile crop.
  function ground(x, lane) {
    const w = innerWidth, h = innerHeight, scale = Math.max(w/1672,h/941);
    const offsetX = (w-1672*scale) * (w <= 800 ? .64 : .5), offsetY = (h-941*scale)/2;
    const px = (x-offsetX)/scale;
    const ridge = [[0,425],[170,480],[380,610],[650,815],[850,900],[1050,740],[1250,550],[1450,395],[1672,475]];
    let y = 475;
    for(let i=1;i<ridge.length;i++) if(px<=ridge[i][0]) { const a= ridge[i-1],b=ridge[i]; y=a[1]+(b[1]-a[1])*(px-a[0])/(b[0]-a[0]); break; }
    return Math.max(65,Math.min(h-65,offsetY+y*scale+lane));
  }
  const goats = Array.from({length:innerWidth < 700 ? 16 : 32}, (_,i) => {
    const el = document.createElement('button'); el.type='button'; el.className='mountain-goat';
    el.innerHTML=art(i); el.setAttribute('aria-label',`Bjergged ${i+1}: træk og kast, eller tryk for at hoppe`);
    layer.append(el);
    const g = {el,x:Math.random()*(innerWidth-65),y:0,vx:(Math.random()>.5?1:-1)*(8+Math.random()*15),vy:0,lane:Math.random()*80-35,air:false,drag:false,angle:0,size:.65+Math.random()*.45};
    g.y=ground(g.x,g.lane);
    let pointer, previous;
    el.addEventListener('pointerdown', e => {
      if(e.button!==0)return;
      pointer=e.pointerId; el.setPointerCapture(pointer); g.drag=true; g.air=false;
      previous={x:e.clientX,y:e.clientY,t:performance.now()}; g.vx=g.vy=0; el.classList.add('is-held'); e.preventDefault();
    });
    el.addEventListener('pointermove', e => {
      if(!g.drag || e.pointerId!==pointer)return;
      const t=performance.now(), dt=Math.max(8,t-previous.t)/1000;
      const dx=e.clientX-previous.x,dy=e.clientY-previous.y;
      g.x=Math.max(0,Math.min(innerWidth-50,g.x+dx));g.y=Math.max(0,Math.min(innerHeight-55,g.y+dy));
      g.vx=Math.max(-1300,Math.min(1300,dx/dt));g.vy=Math.max(-1300,Math.min(1300,dy/dt));
      previous={x:e.clientX,y:e.clientY,t};
    });
    function release(e) {
      if(!g.drag || e.pointerId!==pointer)return;
      g.drag=false;g.air=true;el.classList.remove('is-held');
      if(performance.now()-previous.t>100 || e.type==='pointercancel')g.vx=g.vy=0;
      if(el.hasPointerCapture(pointer))el.releasePointerCapture(pointer);
    }
    el.addEventListener('pointerup',release); el.addEventListener('pointercancel',release); el.addEventListener('lostpointercapture',release);
    el.addEventListener('click',e=>{if(e.detail===0){g.air=true;g.vy=-300;}});
    return g;
  });
  let last=0,raf=0;
  const active=()=>document.documentElement.dataset.theme!=='viking'&&!document.hidden;
  function sync(){
    layer.hidden=!active();layer.inert=!active();
    if(!active()){cancelAnimationFrame(raf);raf=0;last=0;}
    else if(!raf){last=0;raf=requestAnimationFrame(frame);}
  }
  function frame(t) {
    raf=0;if(!active())return;
    const dt=Math.min((t-last)/1000 || 0,.035);last=t;
    if(!document.hidden) {
      if(!document.querySelector('dialog[open]')) for(const g of goats) {
        if(!g.drag) {
          if(g.air) {g.vy+=950*dt;g.x+=g.vx*dt;g.y+=g.vy*dt;g.angle+=g.vx*dt*.15;
            if(g.x<0 || g.x>innerWidth-55){g.x=Math.max(0,Math.min(innerWidth-55,g.x));g.vx*=-.6;}
            const floor=ground(g.x,g.lane);
            if(g.y>=floor && g.vy>0){g.y=floor;g.air=false;g.angle=0;g.vx=(g.vx<0?-1:1)*(8+Math.random()*15);}
          } else if(!reduced.matches&&document.documentElement.dataset.animation!=='false') {g.x+=g.vx*dt;if(g.x<0 || g.x>innerWidth-55)g.vx*=-1;g.x=Math.max(0,Math.min(innerWidth-55,g.x));g.y=ground(g.x,g.lane);}
        }
        g.el.style.transform=`translate(${g.x}px,${g.y}px) rotate(${g.angle}deg) scale(${g.size})`;
        g.el.style.setProperty('--facing',g.vx<0?-1:1);
        g.el.classList.toggle('is-walking',!g.air&&!g.drag&&!reduced.matches&&document.documentElement.dataset.animation!=='false');
      }
    }
    raf=requestAnimationFrame(frame);
  }
  document.addEventListener('visibilitychange',sync);
  document.addEventListener('fjordseed:appearance',sync);
  sync();
})();
