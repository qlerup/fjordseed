/* Decorative trade/raid journeys. Actual traffic and VPN state remain authoritative. */
(() => {
 'use strict';
 const TAU=Math.PI*2;
 class NordicCaravan {
  constructor(){this.parties=[];this.wait=[0,0];this.serial=[0,0];this.started=[false,false];}
  loot(index){return [2,5,8].includes(index%10)?'captive':'gold';}
  advance(delta,rates,ready){
   if(!ready){this.parties=[];this.started=[false,false];return;}
   for(const party of this.parties)party.progress+=delta/12;
   this.parties=this.parties.filter(p=>p.progress<2);
   for(let direction=0;direction<2;direction++){
    if(!rates[direction])continue;
    // Populate the long route on first activity; each traveller then keeps its
    // identity and cargo through polls, rate changes and the VPN crossing.
    if(!this.started[direction]){
     this.started[direction]=true;
     for(const progress of [.08,.53,1.08,1.58])this.launch(direction,progress);
    }
    this.wait[direction]-=delta;
    if(this.wait[direction]<=0){this.launch(direction,0);this.wait[direction]=3.6;}
   }
  }
  launch(direction,progress){
   const id=this.serial[direction]++;
   this.parties.push({direction,progress,id,cargo:this.loot(id)});
  }
  route(direction,link,w,h){
   const town={seed:{x:w*.12,y:h*.51},vpn:{x:w*.5,y:h*.51},torrent:{x:w*.88,y:h*.23},peers:{x:w*.88,y:h*.82}};
   const a=direction?(link?town.vpn:town.seed):(link?town.vpn:town.torrent);
   const b=direction?(link?town.peers:town.vpn):(link?town.seed:town.vpn);
   const bend=(direction?1:-1)*h*.32;
   return {a,b,c:{x:a.x+(b.x-a.x)*.22,y:a.y+bend},d:{x:b.x-(b.x-a.x)*.22,y:b.y+bend}};
  }
  point(path,t){const q=1-t;return {x:q*q*q*path.a.x+3*q*q*t*path.c.x+3*q*t*t*path.d.x+t*t*t*path.b.x,y:q*q*q*path.a.y+3*q*q*t*path.c.y+3*q*t*t*path.d.y+t*t*t*path.b.y};}
  position(party,w,h,offset=0){
   const progress=Math.max(0,Math.min(1.9999,party.progress+offset)),link=Math.floor(progress);
   const path=this.route(party.direction,link,w,h),t=progress-link,p=this.point(path,t);
   const next=this.point(path,Math.min(1,t+.001));
   return {...p,facing:next.x>=p.x?1:-1};
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
   const glow=c.createRadialGradient(0,-15,6,0,-15,88);glow.addColorStop(0,'#b6a36922');glow.addColorStop(1,'#6a754500');c.fillStyle=glow;c.fillRect(-90,-90,180,130);
   this.ellipse(c,0,5,70,21,'#333c2c88');this.ellipse(c,0,6,60,14,'#85724b36');
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
  road(c,path,width){
   c.save();c.lineCap='round';c.lineJoin='round';
   const trace=()=>{c.beginPath();c.moveTo(path.a.x,path.a.y);c.bezierCurveTo(path.c.x,path.c.y,path.d.x,path.d.y,path.b.x,path.b.y);};
   // Soft earthen shoulders and a worn, lighter walking surface.
   for(const [size,color] of [[width+8,'#191b1280'],[width+4,'#555036b8'],[width,'#8b7551eb'],[width*.63,'#a18a603d']]){
    trace();c.strokeStyle=color;c.lineWidth=size;c.stroke();
   }
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
   const scale=w<600?.57:Math.min(1.35,w/800);
   // Sparse grass, stones and barley surround the village roads.
   for(let i=0;i<115;i++){
    const x=18+(i*137.51%(w-36)),y=30+(i*79.31%(h-60));
    if(i%4===0)this.ellipse(c,x,y,2.5,1.2,'#baab7940');
    else {this.line(c,[[x-3,y],[x-1,y-5],[x,y],[x+3,y-4]],'#98a16c30',1);}
   }
   for(let direction=0;direction<2;direction++)for(let link=0;link<2;link++){
    this.road(c,this.route(direction,link,w,h),w<600?13:22);
   }
   this.village(c,w*.12,h*.51,scale);
   this.village(c,w*.5,h*.51,scale*1.08,true);
   this.village(c,w*.88,h*.23,scale);
   this.village(c,w*.88,h*.82,scale);
   this.layer=layer;
  }
  person(c,x,y,s,facing,phase,variant,cargo){
   c.save();c.translate(x,y);c.scale(s*facing,s);
   const captive=variant==='captive',step=Math.sin(phase),bob=Math.abs(Math.cos(phase))*1.3;
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
    this.line(c,[[6,-21],[10,-15+step]],'#c9a57c',3);
    this.line(c,[[10,-14+step],[13,-33+step]],'#ba9766',1.8);
    this.shape(c,[[12,-32+step],[18,-35+step],[18,-28+step],[12,-28+step]],'#b7c6bd','#e1d9bd',.6);
    this.ellipse(c,-5,-18,6,7,variant%2?'#536e6c':'#a35f42');
    c.strokeStyle='#dab880';c.lineWidth=1;c.stroke();this.ellipse(c,-5,-18,2,2,'#c4c2a6');
   }else{
    this.shape(c,[[-5,-33],[-3,-36],[3,-35],[5,-31]],'#73523b',null);
    this.line(c,[[4,-22],[7,-17],[10,-19]],'#d1b08a',2.5);
    this.line(c,[[7,-19],[10,-19]],'#9caaa0',2);
   }
   if(cargo==='gold'){
    this.shape(c,[[-9,-22],[-16,-20],[-19,-9],[-14,-5],[-6,-8],[-5,-17]],'#b3914e','#e3c783',.8);
    this.line(c,[[-15,-21],[-16,-25],[-10,-24],[-11,-21]],'#e2c37c',1.5);
    this.line(c,[[-15,-18],[-12,-16],[-14,-12]],'#eed79b',1);
    this.ellipse(c,-11,-9,1.4,1.4,'#ffe49b');
   }
   c.restore();
  }
  draw(c,w,h,time,ready,rates,still){
   this.backdrop(w,h);c.drawImage(this.layer,0,0,w,h);
   if(!ready)return;
   const scale=w<600?.72:1.05;
   for(const party of [...this.parties].sort((a,b)=>this.position(a,w,h).y-this.position(b,w,h).y)){
    const p=this.position(party,w,h),loaded=party.progress>=1;
    // Fade at gates and hide the instantaneous cargo change inside the VPN town.
    const gateDistance=Math.min(party.progress,Math.abs(party.progress-1),2-party.progress);
    c.save();c.globalAlpha=Math.min(1,gateDistance*18);
    const gait=still?0:time*8+party.id*1.9;
    const follower=this.position(party,w,h,-.045);
    if(loaded&&party.cargo==='captive'){
     const captive=this.position(party,w,h,-.085);
     c.save();c.setLineDash([2,2]);this.line(c,[[p.x-6*p.facing,p.y-15*scale],[captive.x+8*captive.facing*scale,captive.y-18*scale]],'#c4b287',.9);c.restore();
     this.person(c,captive.x,captive.y,scale*.94,captive.facing,gait-.9,'captive');
    }else this.person(c,follower.x,follower.y+4,scale*.92,follower.facing,gait+1.8,party.id+1,loaded?'gold':null);
    this.person(c,p.x,p.y,scale,p.facing,gait,party.id,loaded&&party.cargo==='gold'?'gold':null);
    c.restore();
   }
   // Smoke drifts gently above the four settlements; no fire or combat.
   for(const [x,y] of [[.12,.51],[.5,.51],[.88,.23],[.88,.82]])for(let i=0;i<3;i++){
    const phase=((still?0:time*.18)+i/3)%1;
    this.ellipse(c,w*x+14+Math.sin(phase*4)*4,h*y-39-phase*24,2+phase*4,3+phase*5,`rgba(206,196,162,${(1-phase)*.15})`);
   }
  }
 }
 window.FjordNordicCaravan=NordicCaravan;
})();
