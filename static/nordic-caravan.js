/* Decorative trade/raid journeys. Actual traffic and VPN state remain authoritative. */
(() => {
 'use strict';
 const TAU=Math.PI*2;
 class NordicCaravan {
  constructor(){this.parties=[];this.wait=[0,0];this.serial=[0,0];}
  loot(index){return [2,5,8].includes(index%10)?'captive':'gold';}
  advance(delta,rates,ready){
   if(!ready){this.parties=[];return;}
   for(const party of this.parties)party.progress+=delta/12;
   this.parties=this.parties.filter(p=>p.progress<2.085);
   for(let direction=0;direction<2;direction++){
    if(!rates[direction])continue;
    this.wait[direction]-=delta;
    if(this.wait[direction]<=0){this.launch(direction,0);this.wait[direction]=3.6;}
   }
  }
  launch(direction,progress){
   const id=this.serial[direction]++;
   this.parties.push({direction,progress,id,cargo:this.loot(id)});
  }
  villageScale(w){return w<600?.42:Math.min(1.35,w/800);}
  gate(name,w,h){
   const town={seed:[.12,.48,1],vpn:[.5,.48,1.08],torrent:[.88,.23,1],peers:[.88,.78,1]}[name];
   return {x:w*town[0],y:h*town[1]+24*this.villageScale(w)*town[2]};
  }
  route(direction,link,w,h){
   const a=this.gate(direction?(link?'vpn':'seed'):(link?'vpn':'torrent'),w,h);
   const b=this.gate(direction?(link?'peers':'vpn'):(link?'seed':'vpn'),w,h);
   const sign=Math.sign(b.x-a.x),shoulder=Math.min(95*this.villageScale(w),Math.abs(b.x-a.x)*.34);
   const exit={x:a.x+sign*shoulder,y:a.y},entry={x:b.x-sign*shoulder,y:b.y},bend=(direction?1:-1)*Math.min(h*.30,Math.abs(b.x-a.x)*.55);
   // Leave each front gate along the outside of the palisade before curving.
   const straight=(p,q)=>({a:p,b:q,c:{x:p.x+(q.x-p.x)/3,y:p.y},d:{x:p.x+(q.x-p.x)*2/3,y:q.y}});
   const dx=entry.x-exit.x,crest={x:(exit.x+entry.x)/2,y:(exit.y+entry.y)/2+bend*.75};
   return {a,b,segments:[straight(a,exit),{a:exit,b:crest,c:{x:exit.x+dx*.25,y:exit.y},d:{x:crest.x-dx*.25,y:crest.y}},{a:crest,b:entry,c:{x:crest.x+dx*.25,y:crest.y},d:{x:entry.x-dx*.25,y:entry.y}},straight(entry,b)]};
  }
  point(path,t){
   if(path.segments){const slot=t<.18?0:t<.5?1:t<.82?2:3;return this.point(path.segments[slot],slot===0?t/.18:slot===1?(t-.18)/.32:slot===2?(t-.5)/.32:(t-.82)/.18);}
   const q=1-t;return {x:q*q*q*path.a.x+3*q*q*t*path.c.x+3*q*t*t*path.d.x+t*t*t*path.b.x,y:q*q*q*path.a.y+3*q*q*t*path.c.y+3*q*t*t*path.d.y+t*t*t*path.b.y};
  }
  position(party,w,h,offset=0){
   const progress=party.progress+offset,link=Math.max(0,Math.min(1,Math.floor(progress)));
   const path=this.route(party.direction,link,w,h),t=Math.max(0,Math.min(1,progress-link));
   // The main hall's door is at local (0,6); the road gate remains at (0,24).
   const townScale=this.villageScale(w)*(link===0?1:1.08);
   const endScale=this.villageScale(w)*(link===0?1.08:1);
   const door=(gate,scale)=>({x:gate.x,y:gate.y-18*scale});
   const startDoor=door(path.a,townScale),endDoor=door(path.b,endScale);
   const transition=.09;
   let p,size;
   if(t<transition){
    const u=t/transition;
    p={x:startDoor.x+(path.a.x-startDoor.x)*u,y:startDoor.y+(path.a.y-startDoor.y)*u};size=u;
   }else if(t>1-transition){
    const u=(1-t)/transition;
    p={x:endDoor.x+(path.b.x-endDoor.x)*u,y:endDoor.y+(path.b.y-endDoor.y)*u};size=u;
   }else {p=this.point(path,(t-transition)/(1-2*transition));size=1;}
   return {...p,link,scale:progress<0||progress>=2?0:size,facing:path.b.x>=path.a.x?1:-1};
  }

  shape(c,points,fill,stroke='#241b13',width=1){
   c.beginPath();points.forEach(([x,y],i)=>i?c.lineTo(x,y):c.moveTo(x,y));c.closePath();
   c.fillStyle=fill;c.fill();if(stroke){c.strokeStyle=stroke;c.lineWidth=width;c.stroke();}
  }
  line(c,points,color,width=1){c.beginPath();points.forEach(([x,y],i)=>i?c.lineTo(x,y):c.moveTo(x,y));c.strokeStyle=color;c.lineWidth=width;c.stroke();}
  ellipse(c,x,y,rx,ry,color){c.beginPath();c.ellipse(x,y,rx,ry,0,0,TAU);c.fillStyle=color;c.fill();}
  house(c,x,y,s,church=false){
   c.save();c.translate(x,y);c.scale(s,s);
   this.ellipse(c,0,2,30,6,'#080a0780');
   this.shape(c,[[-23,-2],[-23,-26],[0,-33],[23,-26],[23,-2]],church?'#b5a788':'#775237');
   this.shape(c,[[-28,-25],[0,-49],[29,-25]],church?'#71604b':'#424f40','#b49a68');
   for(let i=0;i<5;i++)this.line(c,[[-20+i*4,-28-i*3],[20-i*4,-28-i*3]],church?'#a48b62':'#8b9870',1);
   this.line(c,[[-22,-22],[-22,-3],[22,-3],[22,-22]],'#c29c68',2);
   for(let i=-14;i<20;i+=8)this.line(c,[[i,-24],[i,-4]],'#3b2a20',1);
   this.shape(c,[[-5,0],[-5,-15],[5,-15],[5,0]],'#171913','#ae8b56');
   for(const wx of [-15,14]){c.fillStyle='#eac27b';c.fillRect(wx-3,-20,6,6);this.line(c,[[wx,-20],[wx,-14]],'#463525');}
   if(church){
    this.shape(c,[[5,-26],[5,-54],[19,-54],[19,-24]],'#c5b899','#6d5b43');
    this.shape(c,[[1,-53],[12,-70],[23,-53]],'#665b4c','#c3aa7b');
    this.line(c,[[12,-80],[12,-65]],'#e0c18a',2);this.line(c,[[7,-75],[17,-75]],'#e0c18a',2);
    c.fillStyle='#242b22';c.fillRect(10,-48,4,9);
   }else{
    this.line(c,[[-28,-25],[-30,-34],[-26,-37]],'#c0a06c',2);
    this.line(c,[[29,-25],[31,-34],[27,-37]],'#c0a06c',2);
   }
   c.restore();
  }
  village(c,x,y,scale,farm=false){
   c.save();c.translate(x,y);c.scale(scale,scale);
   if(farm){
    this.shape(c,[[-65,14],[-31,5],[-5,24],[-39,34]],'#6e6036','#a99556');
    for(let i=0;i<6;i++)this.line(c,[[-58+i*5,15-i],[-36+i*5,30-i]],'#c3a660',1);
   }
   this.house(c,-38,-11,.68);this.house(c,37,-13,.62);this.house(c,0,6,farm?1:.95,farm);
   this.house(c,-37,15,.55);this.house(c,42,19,.52);
   // Palisade posts, a gate, stacked logs and a little well.
   for(let i=-62;i<=62;i+=7){if(Math.abs(i)<13)continue;const yy=24-Math.abs(i)*.09;this.line(c,[[i,yy],[i,yy-10]],'#a28a5a',2);}
   this.line(c,[[-62,19],[-15,23]],'#604a30',2);this.line(c,[[15,23],[62,19]],'#604a30',2);
   this.ellipse(c,23,16,6,3,'#b6a17a');this.ellipse(c,23,15,4,2,'#1b2521');
   this.line(c,[[18,15],[18,5],[28,5],[28,15]],'#b49a6b',1.5);
   for(let i=0;i<3;i++)this.line(c,[[-27+i*2,24],[-14+i*2,24]],'#ba8d54',2);
   if(!farm){this.line(c,[[-12,0],[-12,-53]],'#bda072',1.5);this.shape(c,[[-11,-52],[10,-48],[-11,-40]],'#894c37','#d8b77b');}
   c.restore();
  }
  terrain(c,w,h,towns,paths,width,dpr){
   // Union roads and village plots before tinting each material layer, so
   // translucent shoulders never leave seams across a village entrance.
   const mask=document.createElement('canvas');mask.width=c.canvas.width;mask.height=c.canvas.height;
   const m=mask.getContext('2d');m.scale(dpr,dpr);m.lineCap='round';m.lineJoin='round';
   for(const [size,inset,color] of [[width+8,4,'#191b1280'],[width+4,2,'#555036b8'],[width,0,'#8b7551eb'],[width*.63,-3,'#a18a603d']]){
    m.clearRect(0,0,w,h);m.fillStyle='#fff';m.strokeStyle='#fff';m.lineWidth=size;
    for(const path of paths){
     m.beginPath();m.moveTo(path.a.x,path.a.y);
     for(const section of path.segments)m.bezierCurveTo(section.c.x,section.c.y,section.d.x,section.d.y,section.b.x,section.b.y);
     m.stroke();
    }
    for(const [x,y,scale] of towns)this.ellipse(m,x,y+4*scale,80*scale+inset,40*scale+inset,'#fff');
    m.globalCompositeOperation='source-in';m.fillStyle=color;m.fillRect(0,0,w,h);
    c.drawImage(mask,0,0,w,h);m.globalCompositeOperation='source-over';
   }
  }
  road(c,path,width){
   c.save();
   // Deterministic grit and broken verge stones follow the same curve as feet.
   for(let i=1;i<180;i++){
    const t=i/180,p=this.point(path,t),next=this.point(path,Math.min(1,t+.002));
    const angle=Math.atan2(next.y-p.y,next.x-p.x),nx=-Math.sin(angle),ny=Math.cos(angle);
    const scatter=Math.sin(i*127.1+path.a.x)*width*.43;
    const edge=i%7===0,offset=edge?(i%2?1:-1)*width*.52:scatter;
    this.ellipse(c,p.x+nx*offset,p.y+ny*offset,edge?1.8:.7,edge?1:.45,
     edge?(i%2?'#c0b18a88':'#363c2999'):(i%3?'#d8c39344':'#433b2b55'));
   }
   c.restore();
  }
  backdrop(w,h){
   const key=w+'x'+h;if(this.cacheKey===key)return;
   this.cacheKey=key;const layer=document.createElement('canvas'),dpr=Math.min(devicePixelRatio||1,2);
   layer.width=Math.round(w*dpr);layer.height=Math.round(h*dpr);const c=layer.getContext('2d');c.scale(dpr,dpr);
   const scale=this.villageScale(w);
   // Sparse grass, stones and barley surround the village roads.
   for(let i=0;i<115;i++){
    const x=18+(i*137.51%(w-36)),y=30+(i*79.31%(h-60));
    if(i%4===0)this.ellipse(c,x,y,2.5,1.2,'#baab7940');
    else {this.line(c,[[x-3,y],[x-1,y-5],[x,y],[x+3,y-4]],'#98a16c30',1);}
   }
   const towns=[[w*.12,h*.48,scale],[w*.5,h*.48,scale*1.08,true],[w*.88,h*.23,scale],[w*.88,h*.78,scale]];
   const paths=[];const roadWidth=w<600?13:22;
   for(let direction=0;direction<2;direction++)for(let link=0;link<2;link++)paths.push(this.route(direction,link,w,h));
   this.terrain(c,w,h,towns,paths,roadWidth,dpr);
   for(const path of paths)this.road(c,path,roadWidth);
   for(const town of towns)this.village(c,...town);
   this.layer=layer;
  }
  person(c,x,y,s,facing,phase,variant,cargo){
   c.save();c.translate(x,y);c.scale(s*facing,s);
   const carrying=cargo==='gold'||cargo==='chest',captive=variant==='captive',step=Math.sin(phase),bob=Math.abs(Math.cos(phase))*1.3;
   this.ellipse(c,0,1,8,2.3,'#070b0b66');c.translate(0,-bob);
   const cloth=captive?'#b6a58b':variant%2?'#596c66':'#8e4939';
   const limb=(hip,knee,foot,color)=>this.line(c,[hip,knee,foot],color,3.4);
   limb([-2,-10],[-3+step*3,-5],[-2+step*5,0],'#40342b');
   limb([2,-10],[3-step*3,-5],[3-step*5,0],'#a18b68');
   this.line(c,[[-2+step*5,0],[1+step*5,0]],'#241e18',2);
   this.line(c,[[3-step*5,0],[6-step*5,0]],'#241e18',2);
   this.shape(c,[[-6,-24],[4,-24],[7,-9],[-6,-9]],cloth,'#29251e');
   if(!captive){
    this.shape(c,[[-5,-23],[-10-step,-11],[-4,-9],[0,-22]],'#3b4842','#8a8a65');
    for(let i=0;i<3;i++)this.line(c,[[-3,-21+i*3],[3,-21+i*3]],'#d2c39b80',.8);
   }
   this.line(c,[[-5,-11],[6,-11]],'#c4a668',2);
   this.ellipse(c,0,-28,5,6,'#d3af83');
   this.shape(c,[[-4,-29],[-4,-23],[0,-18],[4,-23],[4,-27]],captive?'#71523c':'#aa7841',null);
   this.ellipse(c,3,-29,.7,.7,'#21251f');
   if(!captive){
    this.shape(c,[[-5,-29],[-4,-35],[0,-37],[5,-34],[6,-29]],'#8a9c96','#d3c7a1',.8);
    this.line(c,[[0,-36],[1,-27]],'#d7cdb0',1);
    if(!carrying){
    this.line(c,[[6,-21],[10,-15+step]],'#c9a57c',3);
    this.line(c,[[10,-14+step],[13,-33+step]],'#ba9766',1.8);
    this.shape(c,[[12,-32+step],[18,-35+step],[18,-28+step],[12,-28+step]],'#b7c6bd','#e1d9bd',.6);
    this.ellipse(c,-5,-18,6,7,variant%2?'#536e6c':'#a35f42');
    c.strokeStyle='#dab880';c.lineWidth=1;c.stroke();this.ellipse(c,-5,-18,2,2,'#c4c2a6');
    }else{
     this.line(c,[[-5,-22],[-9,-17],[-10,-13]],'#d3af83',3);
     this.line(c,[[5,-22],[9,-17],[10,-13]],'#d3af83',3);
    }
   }else{
    this.shape(c,[[-5,-33],[-3,-36],[3,-35],[5,-31]],'#73523b',null);
    this.line(c,[[4,-22],[7,-17],[10,-19]],'#d1b08a',2.5);
    this.line(c,[[7,-19],[10,-19]],'#9caaa0',2);
   }
   if(cargo==='gold'){
    const leather=c.createLinearGradient(-17,-15,13,-8);leather.addColorStop(0,'#513011');leather.addColorStop(.4,'#bc8740');leather.addColorStop(.7,'#d3a452');leather.addColorStop(1,'#704117');
    this.shape(c,[[-7,-23],[-13,-19],[-18,-9],[-17,0],[-9,5],[7,4],[14,-2],[14,-11],[8,-20],[5,-23]],leather,'#e1b367',1);
    this.line(c,[[-12,-15],[-10,-5],[-6,1]],'#6e461e',1.4);
    this.line(c,[[8,-15],[10,-5],[6,1]],'#f0cb7b88',1.3);
    this.ellipse(c,-1,-23,9,3,'#36210b');
    this.gold(c,-1,-24,phase,9);
    this.line(c,[[-10,-20],[-2,-18],[8,-21]],'#f2d395',1.8);
    this.ellipse(c,-11,-14,2,2,'#d3af83');this.ellipse(c,10,-14,2,2,'#d3af83');
   }
   c.restore();
  }
  gold(c,x,y,time,count=12){
   c.save();c.translate(x,y);
   for(let i=0;i<count;i++){
    const px=((i*7)%19)-9,py=-Math.floor(i/4)*2+(i%2);
    const metal=c.createLinearGradient(px-3,py-3,px+3,py+3);
    metal.addColorStop(0,'#fff7c0');metal.addColorStop(.22,'#ffe78a');metal.addColorStop(.46,'#e9ac19');metal.addColorStop(.6,'#fff4b1');metal.addColorStop(1,'#9d5a08');
    this.ellipse(c,px,py,3.8,2.4,metal);c.strokeStyle='#9b640b';c.lineWidth=.55;c.stroke();
   }
   for(let i=0;i<2;i++){
    const glow=.45+.55*Math.pow(Math.max(0,Math.sin(time*1.3+i*2.8)),5),px=i?7:-6,py=i?-5:-2;
    c.save();c.globalAlpha*=glow;c.shadowColor='#ffe377';c.shadowBlur=7;
    this.shape(c,[[px,py-4],[px+.9,py-.8],[px+4,py],[px+.9,py+.8],[px,py+4],[px-.9,py+.8],[px-4,py],[px-.9,py-.8]],'#fffbd5',null);c.restore();
   }
   c.restore();
  }
  chest(c,a,b,s,time){
   const dx=a.x-b.x,dy=a.y-b.y,span=Math.hypot(dx,dy)/s,width=Math.max(22,Math.min(42,span-12));
   c.save();c.translate((a.x+b.x)/2,(a.y+b.y)/2-13*s);c.rotate(Math.atan2(dy,dx));c.scale(s,s);
   this.line(c,[[-span/2+8,0],[span/2-8,0]],'#9a6c33',4);
   const wood=c.createLinearGradient(0,-9,0,12);wood.addColorStop(0,'#a56b2f');wood.addColorStop(1,'#44250e');
   this.shape(c,[[-width/2,-7],[width/2,-7],[width/2,10],[-width/2,10]],wood,'#e6b856',1.2);
   this.shape(c,[[-width/2,-8],[-width/2+2,-18],[width/2-2,-18],[width/2,-8]],'#6a421b','#d9ab4f',1.3);
   this.line(c,[[-width/2+3,-15],[width/2-3,-15]],'#f6d88b',1);
   this.ellipse(c,0,-7,width/2-2,3.5,'#382006');this.gold(c,-5,-7,time,12);this.gold(c,6,-7,time+1,8);
   for(const x of[-width*.32,width*.32]){const metal=c.createLinearGradient(x-2,0,x+2,0);metal.addColorStop(0,'#ab6c11');metal.addColorStop(.5,'#fff0a0');metal.addColorStop(1,'#b27b22');this.shape(c,[[x-2,-6],[x+2,-6],[x+2,10],[x-2,10]],metal,null);}
   this.shape(c,[[-3,0],[3,0],[3,6],[-3,6]],'#ffe49b','#8f5d14',.6);this.ellipse(c,0,3,.8,1.2,'#3c280e');c.restore();
  }
  draw(c,w,h,time,ready,rates,still){
   this.backdrop(w,h);c.drawImage(this.layer,0,0,w,h);
   if(!ready)return;
   const scale=w<600?.72:1.05;
   for(const party of [...this.parties].sort((a,b)=>this.position(a,w,h).y-this.position(b,w,h).y)){
    const p=this.position(party,w,h),loaded=party.progress>=1;
    const gait=still?0:time*8+party.id*1.9;
    const follower=this.position(party,w,h,-.045);
    const drawPerson=(position,phase,variant,cargo,size=1)=>{
     if(position.scale>0)this.person(c,position.x,position.y,scale*position.scale*size,position.facing,phase,variant,cargo);
    };
    if(loaded&&party.cargo==='captive'){
     const captive=this.position(party,w,h,-.085);
     if(follower.link===0)drawPerson(follower,gait+1.8,party.id+1,null,.92);
     // The captive joins at the VPN door, after the leader has emerged.
     if(captive.link===1&&captive.scale>0){
      if(p.scale>0){
       c.save();c.setLineDash([2,2]);this.line(c,[[p.x-6*p.facing*scale*p.scale,p.y-15*scale*p.scale],[captive.x+8*captive.facing*scale*captive.scale,captive.y-18*scale*captive.scale]],'#c4b287',.9);c.restore();
      }
      drawPerson(captive,gait-.9,'captive',null,.94);
     }
    }else if(loaded&&party.cargo==='gold'&&party.id%2===1){
     // Keep carriers and their shared chest together while crossing the doorway.
     const shared=follower.link===1&&p.scale>0&&follower.scale>0;
     drawPerson(follower,gait,party.id+1,follower.link===1?(shared?'chest':'gold'):null);
     drawPerson(p,gait,party.id,shared?'chest':'gold');
     if(shared)this.chest(c,p,follower,scale*Math.min(p.scale,follower.scale),gait);
     continue;
    }else drawPerson(follower,gait+1.8,party.id+1,null,.92);
    drawPerson(p,gait,party.id,loaded&&party.cargo==='gold'?'gold':null);
   }

   // Smoke drifts gently above the four settlements; no fire or combat.
   for(const [x,y] of [[.12,.48],[.5,.48],[.88,.23],[.88,.78]])for(let i=0;i<3;i++){
    const phase=((still?0:time*.18)+i/3)%1;
    this.ellipse(c,w*x+14+Math.sin(phase*4)*4,h*y-39-phase*24,2+phase*4,3+phase*5,`rgba(206,196,162,${(1-phase)*.15})`);
   }
  }
 }
 window.FjordNordicCaravan=NordicCaravan;
})();
