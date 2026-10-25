/* Live transfer scene. Decorative only; rates and VPN state come from app.js. */
(() => {
 'use strict';
 const TAU=Math.PI*2;
 const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
 const svgElement=(tag,attributes={})=>{const el=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attributes))el.setAttribute(key,value);return el;};
 class TransferFlow {
  constructor(root){
   this.root=root;this.canvas=root.querySelector('.flow-canvas');
   this.ctx=this.canvas.getContext('2d');
   this.ready=false;this.rates=[0,0];this.energy=[0,0];this.frame=null;
   this.visible=false;this.width=0;this.height=0;this.points=[];this.paths=[];
   this.packets=[];
   this.rateHistory=[];this.rateMaximum=[null,null];this.rateRenderedAt=null;
   this.rateCharts=[...root.querySelectorAll('.flow-rate')].map((card,index)=>{
    const svg=svgElement('svg',{viewBox:'0 0 300 100',preserveAspectRatio:'none',class:'flow-rate-chart','aria-hidden':'true'});
    const defs=svgElement('defs'),gradient=svgElement('linearGradient',{id:'flow-rate-fill-'+index,x1:0,y1:0,x2:0,y2:1});
    gradient.append(svgElement('stop',{offset:'0%','stop-color':'currentColor','stop-opacity':'.24'}),svgElement('stop',{offset:'100%','stop-color':'currentColor','stop-opacity':'.02'}));defs.append(gradient);
    const fill=svgElement('path',{fill:`url(#flow-rate-fill-${index})`}),line=svgElement('path',{class:'flow-rate-curve'});
    svg.append(defs,fill,line);card.prepend(svg);return {svg,fill,line};
   });
   this.core=root.querySelector('.flow-core-shell');this.pulse=null;
   this.lanes=Array.from({length:6},(_,index)=>({direction:Math.floor(index/3),strand:index%3,wait:Math.random()*.8}));
   this.motion=matchMedia('(prefers-reduced-motion: reduce)');
   this.tick=this.tick.bind(this);
   this.motion.addEventListener('change',()=>this.sync());
   document.addEventListener('visibilitychange',()=>this.sync());
   this.resizeObserver=new ResizeObserver(()=>this.resize());
   this.resizeObserver.observe(this.canvas);
   this.observer=new IntersectionObserver(entries=>{
    this.visible=entries[0].isIntersecting;this.sync();
   });
   this.observer.observe(root);
  }
  update({ready,download,upload}){
   this.ready=!!ready;
   this.recordRates([download,upload]);
   if(!this.ready)this.packets=[];
   this.rates=[download,upload].map(rate=>this.ready&&Number.isFinite(rate)&&rate>0?rate:0);
   const levels=this.rates.map(rate=>rate?clamp(Math.log2(1+rate/16384)/14,.08,1):0);
   this.target=levels;
   this.root.dataset.traffic=this.rates.some(Boolean)?'moving':'idle';
   this.root.style.setProperty('--flow-energy',Math.max(...levels).toFixed(3));
   this.sync();
  }
  recordRates(rates,now=Date.now()){
   const values=rates.map(rate=>this.ready&&Number.isFinite(rate)&&rate>=0?rate:null);
   const last=this.rateHistory.at(-1);
   // UI rerenders are not additional observations. Missing status is never zero.
   const sample={at:now,values};
   if(last&&now-last.at<250)this.rateHistory[this.rateHistory.length-1]=sample;
   else this.rateHistory.push(sample);
   // Keep the point just outside the visible window so its tail can scroll out.
   this.rateHistory=this.rateHistory.filter(point=>point.at>=now-62000).slice(-125);
   this.drawRates(now);
  }
  drawRates(now=Date.now()){
   const latest=this.rateHistory.at(-1);if(!latest)return;
   const instant=this.motion.matches||!this.visible||document.hidden;
   const elapsed=Math.max(0,(now-(this.rateRenderedAt??now))/1000);this.rateRenderedAt=now;
   const blend=instant?1:1-Math.exp(-elapsed*5);
   // A one-second playback buffer lets measurements slide through a continuous
   // timeline, instead of snapping the previous endpoint left on each response.
   const playhead=instant?now:now-1000;
   const points=this.rateHistory.filter(point=>point.at<=playhead);
   const previous=points.at(-1),next=this.rateHistory.find(point=>point.at>playhead);
   if(previous&&playhead>previous.at&&playhead-previous.at<=12000){
    const fraction=next&&next.at-previous.at<=12000?(playhead-previous.at)/(next.at-previous.at):0;
    points.push({at:playhead,values:previous.values.map((value,i)=>value===null?null:next?.values[i]!=null?value+(next.values[i]-value)*fraction:value)});
   }
   this.rateCharts.forEach(({svg,fill,line},index)=>{
    svg.classList.toggle('is-unavailable',latest.values[index]===null);
    const start=playhead-60000;
    const activity=points.some((point,i)=>point.values[index]>0&&
     (point.at>=start||(points[i+1]?.at>start&&points[i+1].values[index]!==null&&points[i+1].at-point.at<=12000)));
    const incoming=latest.values[index]>0&&latest.at>playhead;
    svg.classList.toggle('is-idle',!activity&&!incoming);
    const target=Math.max(1,...this.rateHistory.filter(point=>point.at>=now-60000).map(point=>point.values[index]??0));
    this.rateMaximum[index]=this.rateMaximum[index]===null?target:this.rateMaximum[index]+(target-this.rateMaximum[index])*blend;
    const maximum=Math.max(1,this.rateMaximum[index]);
    const x=point=>300-(playhead-point.at)/60000*300,y=point=>94-clamp(point.values[index]/maximum,0,1)*68;
    let previous=null,path='',area='',segment=[];
    const flush=()=>{
     if(!segment.length)return;
     let d=`M${x(segment[0])},${y(segment[0])}`;
     for(let i=1;i<segment.length;i++){
      const a=segment[i-1],b=segment[i],mid=(x(a)+x(b))/2;
      d+=` C${mid},${y(a)} ${mid},${y(b)} ${x(b)},${y(b)}`;
     }
     path+=d;area+=d+` L${x(segment.at(-1))},100 L${x(segment[0])},100 Z`;segment=[];
    };
    for(const point of points){
     if(point.values[index]===null){flush();previous=null;continue;}
     if(previous&&point.at-previous.at>12000)flush();
     segment.push(point);previous=point;
    }
    flush();line.setAttribute('d',path);fill.setAttribute('d',area);
   });
  }
  resize(){
   if(!this.ctx)return;
   const rect=this.canvas.getBoundingClientRect();
   if(!rect.width||!rect.height)return;
   this.width=rect.width;this.height=rect.height;
   const dpr=Math.min(devicePixelRatio||1,2);
   this.canvas.width=Math.round(rect.width*dpr);this.canvas.height=Math.round(rect.height*dpr);
   this.ctx.setTransform(dpr,0,0,dpr,0,0);
   this.points=[...this.root.querySelectorAll('.flow-node .flow-icon')].map(el=>{
    const r=el.getBoundingClientRect();return {x:r.left+r.width/2-rect.left,y:r.top+r.height/2-rect.top};
   });
   this.paths=[];
   // Each route is ordered from sender to receiver, through the VPN.
   for(const [direction,route] of [[0,[2,1,0]],[1,[0,1,3]]]){
    for(let link=0;link<2;link++){
     for(let strand=0;strand<3;strand++){
      const a=this.points[route[link]],b=this.points[route[link+1]];
      if(!a||!b)continue;
      const lift=(direction?1:-1)*(12+strand*9);
      this.paths.push({direction,strand,link,a,b,
       c:{x:a.x+(b.x-a.x)*.32,y:a.y+lift},d:{x:b.x-(b.x-a.x)*.32,y:b.y+lift}});
     }
    }
   }
   this.draw(performance.now()/1000);this.sync();
  }
  sync(){
   const animate=this.ctx&&this.ready&&this.visible&&!document.hidden&&!this.motion.matches;
   this.root.classList.toggle('flow-paused',!animate);
   if(animate&&this.frame===null){this.last=performance.now();this.frame=requestAnimationFrame(this.tick);}
   if(!animate){
    this.pulse?.cancel();this.pulse=null;
    if(this.frame!==null)cancelAnimationFrame(this.frame);
    this.frame=null;this.energy=this.target||[0,0];this.draw(performance.now()/1000);this.drawRates();
   }
  }
  tick(now){
   this.frame=null;
   const delta=Math.min((now-this.last)/1000,.1);this.last=now;
   this.energy=this.energy.map((level,i)=>level+((this.target?.[i]||0)-level)*Math.min(1,delta*4));
   this.advance(delta);
   this.draw(now/1000);
   this.drawRates();
   this.frame=requestAnimationFrame(this.tick);
  }
  advance(delta){
   // Packets keep their own pace across both links, including after traffic stops.
   let arrivals=0;
   for(const packet of this.packets){
    const before=packet.progress;packet.progress+=delta*packet.speed;
    if(before<1&&packet.progress>=1)arrivals++;
   }
   if(arrivals)this.pulseShield();
   this.packets=this.packets.filter(packet=>packet.progress<2);
   for(const lane of this.lanes){
    if(!this.rates[lane.direction])continue;
    lane.wait-=delta;
    if(lane.wait>0)continue;
    this.packets.push({direction:lane.direction,strand:lane.strand,progress:0,
     speed:.24+Math.random()*.1,level:this.target[lane.direction]});
    // Independent launch times avoid synchronized rows on the three strands.
    lane.wait=.65+Math.random()*.65;
   }
  }
  pulseShield(){
   if(!this.core||!this.ready||!this.visible||document.hidden||this.motion.matches)return;
   // Merge simultaneous arrivals into one bounded pulse, starting at its current
   // appearance so a second packet never snaps the shield back to its base size.
   const current=getComputedStyle(this.core);
   const start={transform:current.transform,filter:current.filter};
   this.pulse?.cancel();
   this.pulse=this.core.animate([
    start,
    {transform:'scale(1.075)',filter:'drop-shadow(0 0 12px #79f8c480)',offset:.28},
    {transform:'scale(1)',filter:'drop-shadow(0 0 0px #79f8c400)'}
   ],{duration:560,easing:'ease-out'});
  }
  point(path,t){
   const q=1-t;
   return {x:q*q*q*path.a.x+3*q*q*t*path.c.x+3*q*t*t*path.d.x+t*t*t*path.b.x,
    y:q*q*q*path.a.y+3*q*q*t*path.c.y+3*q*t*t*path.d.y+t*t*t*path.b.y};
  }
  stroke(path,start,end,color,width){
   const c=this.ctx;c.beginPath();
   for(let j=0;j<=14;j++){
    const p=this.point(path,start+(end-start)*j/14);
    j?c.lineTo(p.x,p.y):c.moveTo(p.x,p.y);
   }
   c.strokeStyle=color;c.lineWidth=width;c.stroke();
  }
  draw(time){
   const c=this.ctx,w=this.width,h=this.height;if(!c||!w||!h)return;
   c.clearRect(0,0,w,h);
   const active=this.ready,still=this.motion.matches||!active;
   if(still)time=0;
   // Quiet constellation and an illuminated tunnel behind the gateway.
   const center=this.points[1]||{x:w/2,y:h*.4};
   const halo=c.createRadialGradient(center.x,center.y,12,center.x,center.y,Math.min(w*.45,300));
   halo.addColorStop(0,active?'#49deb51c':'#d7ad4b09');halo.addColorStop(1,'#49deb500');
   c.fillStyle=halo;c.fillRect(0,0,w,h);
   for(let i=0;i<48;i++){
    const x=((i*137.51)%997)/997*w,y=12+((i*71.23)%211)/211*(h-30);
    const pulse=still?.35:.3+.25*Math.sin(time*.7+i);
    c.fillStyle=`rgba(130,190,199,${pulse*.55})`;c.beginPath();c.arc(x,y,i%7===0?1.4:.7,0,TAU);c.fill();
    if(i%3===0){c.strokeStyle='#84b9c609';c.lineWidth=.5;c.beginPath();c.moveTo(x,y);c.lineTo(x+26,y-14);c.lineTo(x+50,y-14);c.stroke();}
   }
   c.lineCap='round';
   for(const path of this.paths){
    const i=path.direction,level=this.energy[i],color=i?'100,174,255':'102,246,191';
    this.stroke(path,0,1,active?`rgba(${color},${.09+level*.12})`:'#71808a25',.8);
    if(!active)continue;
    for(const packet of this.packets){
     if(packet.direction!==i||packet.strand!==path.strand||Math.floor(packet.progress)!==path.link)continue;
     const t=packet.progress-path.link;
     const tail=clamp(t-.12,0,1);
     const alpha=Math.sin(t*Math.PI)*(.55+packet.level*.4);
     this.stroke(path,tail,t,`rgba(${color},${alpha*.07})`,11);
     this.stroke(path,tail,t,`rgba(${color},${alpha*.28})`,3.5);
     this.stroke(path,clamp(t-.035,0,1),t,`rgba(${color},${alpha})`,1.5);
     const p=this.point(path,t);c.fillStyle=`rgba(${color},${alpha})`;
     c.beginPath();c.arc(p.x,p.y,1.7+packet.level*.7,0,TAU);c.fill();
    }
   }
   // Receiving nodes echo the actual direction of traffic, never idle traffic.
   if(active)for(const [i,index] of [[0,0],[1,3]]){
    if(!this.rates[i]||!this.points[index])continue;
    const p=this.points[index],phase=(time*.6)%1;
    c.strokeStyle=i?`rgba(100,174,255,${(1-phase)*.28})`:`rgba(102,246,191,${(1-phase)*.28})`;
    c.lineWidth=1;c.beginPath();c.arc(p.x,p.y,34+phase*22,0,TAU);c.stroke();
   }
  }
 }
 window.FjordTransferFlow=TransferFlow;
})();
