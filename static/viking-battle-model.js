/* Five minutes of visible, unpaused time. Coordinates are feet on the ground. */
(() => {
 'use strict';
 const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
 class Battle {
  static DURATION=300;
  static RETREAT=270;
  static CLEAR=296;
  static LAND=.66;
  constructor(count=64,random=Math.random,village=false){this.village=village;this.count=count;this.vikingCount=village?Math.min(Math.floor(count/2),count<64?9:12):Math.floor(count/2);this.random=random;this.round=0;this.reset();}
  range(a,b){return a+(b-a)*this.random();}
  reset(){
   this.time=0;this.round++;this.effects=[];this.effectId=0;this.arrows=[];this.arrowId=0;this.houseEncounterId=0;
   this.exitStart=null;this.raidStart=null;this.returnStart=null;this.sailStart=null;this.departureEnd=null;this.winner=null;this.trails=[];this.trailId=0;this.rocks=[];this.rockId=0;
   this.settlement=[{id:0,x:.12,y:.72,church:true},{id:1,x:.075,y:.86},{id:2,x:.23,y:.80},{id:3,x:.23,y:.95}];
   if(this.village)this.settlement=[{id:0,x:.12,y:.73,church:true},...[[.06,.85],[.20,.83],[.34,.76],[.34,.91],[.09,.97],[.23,.98],[.48,.81],[.49,.97]].map(([x,y],i)=>({id:i+1,x,y,variant:i%3}))];
   const strategies=['shieldwall','wedge','flank'];
   this.strategies=[0,1].map(()=>strategies[Math.floor(this.random()*strategies.length)]);
   this.formations=this.strategies.map(()=>{
    const selected=[];let pool=[];
    for(let i=0;i<Math.ceil(this.count/16);i++){
     if(!pool.length)pool=[...strategies];
     selected.push(pool.splice(Math.floor(this.random()*pool.length),1)[0]);
    }
    return selected;
   });
   const fleetSize=this.village?3:5+Math.floor(this.random()*4);
   this.boats=Array.from({length:fleetSize},(_,id)=>{
    const delay=Math.floor(id/2)*3.8+(id%2)*1.2,duration=this.range(24,28);
    return {id,team:1,entryX:id%2?.76:.28,x:id%2?.76:.28,y:.35,scale:.15,
     dock:.31+id/(fleetSize-1)*.40,dockY:.55+(id%2)*.028,delay,duration,bend:this.range(-.009,.009),
     landAt:delay+duration+1,visible:true};
   });
   this.arrivalEnd=Math.max(...this.boats.map(b=>b.landAt))+6;
   this.catapults=Array.from({length:4},(_,id)=>{
    const team=id>=2?1:0,dock=team?this.range(.77,.88):this.range(.07,.15);
    return {id,team,x:team?1.2:dock,y:.76+(id%2)*.17,dock,enterAt:team?this.arrivalEnd+this.range(4,12):0,
     nextShot:this.arrivalEnd+this.range(8,16),shotAt:-10,exitX:null};
   });
   if(this.village)this.catapults=[];
   const unitCount=this.village?Math.ceil(this.count/2)+this.vikingCount:this.count;
   this.units=Array.from({length:unitCount},(_,id)=>{
    const team=this.village&&id>=this.vikingCount*2?0:id%2;
    const rank=this.village&&id>=this.vikingCount*2?id-this.vikingCount:Math.floor(id/2);
    const lane=rank%4,entryX=team?1.12+id*.006:-.12-id*.006;
    const boat=team===1?Math.floor(id/2)%fleetSize:null;
    const squad=Math.floor(rank/8),slot=rank%8,archer=(!this.village||team===1)&&id%8<2;
    const strategy=this.formations[team][squad];
    const centerX=.17+(squad%2)*.19,centerY=.685+Math.floor(squad/2)*.14;
    const column=Math.floor(slot/4),front=strategy==='wedge'?-.018*Math.abs(lane-1.5):strategy==='flank'?.012*lane:0;
    const targetX=centerX+front-column*.03-(archer?.035:0)+this.range(-.004,.004);
    const targetY=centerY+lane*.032;
    const seats=boat===null?0:Math.ceil((this.vikingCount-boat)/fleetSize),seat=Math.floor(rank/fleetSize);
    return {id,rank,team,lane,squad,boat,seatOffset:(seat-(seats-1)/2)*Math.min(26,150/Math.max(1,seats-1)),archer,spearman:(!this.village||team===1)&&!archer&&rank%3===1,strategy,civilian:this.village&&team===0,female:rank%2===0,fleeDelay:this.range(0,7),
     x:team?this.boats[boat].x:targetX+.16,y:team?.35:targetY,entryX,
     targetX:team?1-targetX:targetX+.16,targetY,bend:this.range(-.015,.015),
     speed:this.range(32,57),decisionAt:0,side:0,enemyId:null,
     facing:team?-1:1,state:team?'sailing':'guarding',deadAt:null,exitX:null,
     jumpAt:-10,nextJump:this.range(4,12),jumpHeight:this.range(12,25),
     attackAt:-10,attackStyle:'overhead',attackDuration:.8,impactDelay:.34,nextAttack:this.range(15,19),struck:true,hp:3+Math.floor(this.random()*3),hitAt:-10};
   });
   if(this.village)for(const u of this.units.filter(u=>u.civilian)){
    const house=this.settlement[1+u.rank%(this.settlement.length-1)];
    u.x=u.targetX=clamp(house.x+this.range(-.025,.04),.035,.55);
    u.y=u.targetY=clamp(house.y+this.range(.005,.025),Battle.LAND,.98);
    u.y=u.targetY=Math.min(u.y,.95);u.seekShelter=u.rank%3!==0;
   }
  }
  get phase(){
   if(this.returnStart!==null)return this.sailStart===null?'boarding':this.time<this.departureEnd-1?'departure':'clear';
   if(this.village&&this.winner===1&&this.exitStart!==null&&this.time>=this.exitStart)return 'boarding';
   if(this.raidStart!==null&&this.time<this.exitStart)return 'raid';
   if(this.exitStart!==null)return this.time<this.exitStart+12?'retreat':'clear';
   return this.time<this.arrivalEnd?'arrival':this.time<Battle.RETREAT?'battle':this.time<Battle.CLEAR?'retreat':'clear';
  }
  checkVictory(){
   if(this.phase!=='battle'||this.settlement.some(h=>h.encounter))return;
   const teams=new Set(this.units.filter(u=>u.deadAt===null&&!u.withdrawing&&!u.sheltered&&u.capturedBy==null&&u.state!=='offscreen').map(u=>u.team));
   if(teams.size>1)return;
   this.winner=teams.size?[...teams][0]:null;this.raidStart=this.winner===1?this.time:null;
   this.exitStart=this.time+(this.winner===1?18:0);this.arrows=[];this.rocks=[];
   const leader=this.units.find(u=>u.deadAt===null&&!u.withdrawing&&u.team===this.winner);
   const pool=this.units.filter(u=>u.team===1&&u.deadAt===null&&!u.withdrawing&&u.captiveId==null),raiders=new Set();
   while(pool.length&&raiders.size<6){const index=Math.floor(this.random()*pool.length);raiders.add(pool.splice(index,1)[0].id);}
   for(const u of this.units){
    if(u.deadAt!==null||u.civilian)continue;
    u.exitX=u.x;u.enemyId=null;u.attackAt=-10;u.shotAt=-10;u.jumpAt=-10;u.nextJump=Infinity;
    u.facing=u.team?1:-1;u.state='running';u.flag=u===leader;
    if(this.winner===1&&raiders.has(u.id)){
     u.raidFromX=u.x;u.raidFromY=u.y;u.raidHouse=this.settlement[1+(Math.floor(u.id/2)%(this.settlement.length-1))].id;
     u.raidDelay=this.range(0,2);u.raidDuration=this.range(7,10);u.loot=false;
    }
   }
  }
  blood(u,direction=1,limb=null){
   this.effects.push({id:++this.effectId,unitId:u.id,x:u.x,y:u.y,at:this.time,direction,seed:this.random(),limb});
   if(this.effects.length>40)this.effects.shift();
  }
  bleed(u){
   if(u.deadAt!==null||(!u.lostArm&&!u.lostLeg)||u.x<0||u.x>1||u.y<Battle.LAND||u.state==='offscreen')return;
   if(this.time<(u.nextBleed??0))return;
   u.nextBleed=this.time+this.range(.25,.48);
   this.trails.push({id:++this.trailId,x:u.x,y:u.y,at:this.time,seed:this.random()});
   if(this.trails.length>240)this.trails.shift();
  }
  wound(u,direction,axe=false){
   if(u.deadAt!==null)return;
   let limb=null;
   if(axe&&u.hp<=1&&this.random()<.22){u.lostHead=true;limb='head';}
   else if(axe&&this.random()<.18){
    if(!u.lostArm&&this.random()<.5){u.lostArm=true;limb='arm';}
    else if(!u.lostLeg){u.lostLeg=true;limb='leg';}
   }
   u.hitAt=this.time;this.blood(u,direction,limb);u.hp--;
   if(u.hp<=0)this.kill(u.id);
   else if(limb&&!u.withdrawing&&!u.civilian){
    u.withdrawing=true;u.withdrawAt=this.time;u.withdrawX=u.x;u.enemyId=null;u.attackAt=-10;u.shotAt=-10;u.nextJump=Infinity;u.state='running';u.facing=u.team?1:-1;
    this.releaseCaptive(u);
   }
   this.checkVictory();
  }
  kill(id){
   const u=this.units[id];if(!u||u.deadAt!==null||this.phase==='clear')return false;
   u.diedInside=u.state==='hiding';u.deadAt=this.time;u.state='fallen';u.jumpAt=-10;this.releaseCaptive(u);if(!u.diedInside)this.blood(u,u.facing);this.checkVictory();return true;
  }
  move(u,dx,dy,dt,width,height,speed=u.speed){
   const gait=u.lostLeg?.24+.22*Math.max(0,Math.sin(this.time*5+u.id)):1;
   const distance=Math.hypot(dx,dy)||1,step=Math.min(distance,dt*speed*gait);
   let nx=clamp(u.x+dx/distance*step/width,.025,.975),ny=clamp(u.y+dy/distance*step/height,Battle.LAND,.95);
   for(const other of this.units){
    if(other.id===u.id||other.deadAt!==null||other.withdrawing||other.capturedBy!=null||['sailing','hiding','inside'].includes(other.state)||other.sheltered)continue;
    const ox=(nx-other.x)*width,oy=(ny-other.y)*height;
    const contact=width<700?21:27;
    if(other.team!==u.team&&Math.abs(oy)<18&&Math.abs(ox)<contact){
     // Never walk through an enemy to reach a previously selected opponent.
     if(Math.abs((u.x-other.x)*width)>=contact)nx=other.x+Math.sign(u.x-other.x)*contact/width;
     else nx=u.x;
     u.enemyId=other.id;u.decisionAt=this.time+1;break;
    }
    if(other.team===u.team&&Math.hypot(ox,oy)<(u.enemyId===other.enemyId?14:21)){
     nx=u.x;ny=clamp(u.y+(u.id>other.id?1:-1)*dt*15/height,Battle.LAND,.95);
    }
   }
   u.x=nx;u.y=ny;u.state='running';
  }
  panic(u,dt,width,height){
   if(u.state==='hiding'||u.sheltered)return;
   const alarm=this.arrivalEnd-8+u.fleeDelay;
   if(this.time<alarm){u.x=u.targetX+Math.sin(this.time*.3+u.id)*.008;u.state='guarding';return;}
   if(u.seekShelter&&this.time>alarm+3+u.fleeDelay&&u.houseId===undefined){
    const houses=this.settlement.filter(h=>!h.church);
    u.houseId=houses.reduce((a,b)=>Math.hypot((a.x-u.x)*width,(Math.min(a.y,.95)-u.y)*height)<Math.hypot((b.x-u.x)*width,(Math.min(b.y,.95)-u.y)*height)?a:b).id;
   }
   let tx,ty;
   if(u.houseId!==undefined){const house=this.settlement[u.houseId];tx=house.x;ty=Math.min(house.y,.95);}
   else{
    if(this.time>=(u.panicAt??0)||Math.hypot((u.panicX-u.x)*width,(u.panicY-u.y)*height)<10){
     const threat=this.units.filter(e=>e.team===1&&e.deadAt===null&&e.state!=='sailing').reduce((a,b)=>!a||Math.hypot((b.x-u.x)*width,(b.y-u.y)*height)<Math.hypot((a.x-u.x)*width,(a.y-u.y)*height)?b:a,null);
     u.panicX=clamp(u.x+this.range(-.13,.13)+(threat?Math.sign(u.x-threat.x)*.06:0),.045,.61);
     u.panicY=clamp(u.y+this.range(-.12,.12),.70,.95);u.panicAt=this.time+this.range(.8,2.1);
    }
    tx=u.panicX;ty=u.panicY;
   }
   const dx=(tx-u.x)*width,dy=(ty-u.y)*height,distance=Math.hypot(dx,dy),step=Math.min(distance,dt*(24+u.fleeDelay)*(u.lostLeg?.35:1));
   if(distance>0){u.x=clamp(u.x+dx/distance*step/width,.035,.63);u.y=clamp(u.y+dy/distance*step/height,.70,.95);if(Math.abs(dx)>1)u.facing=dx<0?-1:1;}
   u.state='running';
   if(u.houseId!==undefined&&distance<=step+3){u.x=tx;u.y=ty;u.state='hiding';u.jumpAt=-10;}
  }
  houseEncounters(){
   for(const house of this.settlement){
    const encounter=house.encounter;if(!encounter||this.time<encounter.until)continue;
    const resident=this.units[encounter.resident],visitor=this.units[encounter.visitor];
    if(visitor.deadAt===null&&resident.deadAt===null){
     if(encounter.type==='hearts')resident.sheltered=true;
     else this.kill(resident.id);
    }
    house.encounter=null;
    if(visitor.deadAt===null){visitor.state='running';visitor.enemyId=null;visitor.visitingHouse=null;visitor.x=house.x+.025;visitor.y=Math.min(house.y+.012,.95);visitor.decisionAt=0;}
   }
  }
  enterHouse(u,enemy,dt,width,height){
   const house=this.settlement[enemy.houseId],y=Math.min(house.y,.95);
   if(house.encounter){u.state='guarding';u.enemyId=null;u.decisionAt=0;return;}
   const dx=(house.x-u.x)*width,dy=(y-u.y)*height;
   if(Math.hypot(dx,dy)>9){u.facing=dx<0?-1:1;this.move(u,dx,dy,dt,width,height);return;}
   const until=this.time+this.range(4.5,6),type=this.signalHouse(house,until+1.5);
   house.encounter={resident:enemy.id,visitor:u.id,type,until};
   u.x=house.x;u.y=y;u.state='inside';u.visitingHouse=house.id;u.attackAt=-10;u.shotAt=-10;
  }
  signalHouse(house,until,type=null){
   house.symbolType=type??(this.houseEncounterId++%2===0?'hearts':'skulls');
   house.symbolUntil=Math.max(house.symbolUntil??0,until);return house.symbolType;
  }
  returnToBoat(u,width,height){
   const boat=this.boats[u.boat],seat=u.seatOffset*boat.scale/width;
   if(u.returnAt===undefined){
    u.returnAt=this.time;u.returnX=u.x;u.returnY=u.y;
    u.returnDuration=clamp(Math.hypot((boat.dock+seat-u.x)*width,(Battle.LAND-u.y)*height)/Math.max(55,u.speed),4,18);
    u.enemyId=null;u.attackAt=-10;u.shotAt=-10;u.jumpAt=-10;u.nextJump=Infinity;
   }
   const age=this.time-u.returnAt,p=clamp(age/u.returnDuration,0,1);
   if(p<1){
    u.x=u.returnX+(boat.dock+seat-u.returnX)*p;u.y=u.returnY+(Battle.LAND-u.returnY)*p;
    u.facing=boat.dock+seat<u.returnX?-1:1;u.state='running';return;
   }
   const leap=clamp((age-u.returnDuration)/1.2,0,1);
   u.x=boat.x+seat;u.y=Battle.LAND+(boat.y-18*boat.scale/height-Battle.LAND)*leap;
   u.state=leap<1?'boarding':'aboard';
   if(leap<1){u.jumpAt=u.returnAt+u.returnDuration;u.jumpHeight=36;}
   else{u.jumpAt=-10;u.facing=boat.entryX<boat.dock?-1:1;}
  }
  capture(raider,resident){
   if(!this.village||raider.team!==1||raider.deadAt!==null||raider.captiveId!=null||!resident.civilian||resident.deadAt!==null||resident.capturedBy!=null||resident.sheltered||resident.state==='hiding')return false;
   raider.captiveId=resident.id;raider.enemyId=null;raider.attackAt=-10;raider.shotAt=-10;raider.jumpAt=-10;
   resident.capturedBy=raider.id;resident.boat=raider.boat;resident.seatOffset=raider.seatOffset+12;resident.state='captive';resident.jumpAt=-10;delete resident.houseId;
   this.checkVictory();return true;
  }
  releaseCaptive(escort){
   const captive=this.units[escort.captiveId];
   if(!captive||captive.capturedBy!==escort.id||captive.state==='aboard')return;
   captive.capturedBy=null;escort.captiveId=null;captive.state='running';captive.panicAt=0;
  }
  updateCaptives(dt,width,height){
   for(const captive of this.units.filter(u=>u.capturedBy!=null&&u.deadAt===null)){
    const escort=this.units[captive.capturedBy],boat=this.boats[captive.boat];
    if((escort.deadAt!==null||escort.withdrawing)&&captive.state!=='aboard'){
     this.releaseCaptive(escort);continue;
    }
    if(escort.state==='aboard'||captive.state==='aboard'){
     captive.state='aboard';captive.x=boat.x+captive.seatOffset*boat.scale/width;captive.y=boat.y-18*boat.scale/height;
    }else{
     const tx=clamp(escort.x-escort.facing*52/width,.035,.975),ty=Math.max(Battle.LAND,escort.y+.006);
     const dx=(tx-captive.x)*width,dy=(ty-captive.y)*height,distance=Math.hypot(dx,dy),step=Math.min(distance,dt*90);
     if(distance){captive.x+=dx/distance*step/width;captive.y+=dy/distance*step/height;}
     captive.state=distance>2?'captive':'captive-waiting';
    }
    captive.facing=escort.facing;
   }
  }
  advance(dt,width=1600,height=1000){
   if(!Number.isFinite(dt)||dt<=0)return;
   this.time+=dt;
   if(this.village&&this.returnStart===null&&(this.phase==='boarding'||this.phase==='retreat'&&this.units.some(u=>u.team===1&&u.deadAt===null&&!u.withdrawing))){this.returnStart=this.time;this.arrows=[];this.rocks=[];}
   const resetAt=this.returnStart!==null?(this.departureEnd??Infinity):(this.exitStart===null?Battle.DURATION:this.exitStart+13);
   if(this.time>=resetAt){this.reset();return;}
   this.houseEncounters();this.checkVictory();
   this.effects=this.effects.filter(e=>this.time-e.at<4);
   this.trails=this.trails.filter(e=>this.time-e.at<18);
   width=Math.max(320,width);height=Math.max(320,height);
   for(const arrow of this.arrows){
    if(!arrow.landed&&this.time-arrow.at>=arrow.duration){
     arrow.landed=true;const target=this.units[arrow.target];
     if((this.phase==='battle'||this.village&&this.phase==='arrival')&&target.deadAt===null&&target.capturedBy==null&&!target.sheltered&&!['offscreen','hiding'].includes(target.state)&&Math.hypot((target.x-arrow.tx)*width,(target.y-arrow.ty)*height)<26&&this.random()<.55){
      this.wound(target,arrow.direction);
     }
    }
   }
   this.arrows=this.arrows.filter(a=>this.time-a.at<a.duration+.4);
   for(const rock of this.rocks){
    if(!rock.landed&&this.time-rock.at>=rock.duration){
     rock.landed=true;
     if(this.phase==='battle')for(const victim of this.units.filter(u=>u.team!==rock.team&&u.deadAt===null&&!u.withdrawing&&Math.hypot((u.x-rock.tx)*width,(u.y-rock.ty)*height)<32).slice(0,3)){
      this.wound(victim,rock.team?-1:1);
     }
    }
   }
   this.rocks=this.rocks.filter(r=>this.time-r.at<r.duration+.5);
   for(const cart of this.catapults){
    if(this.phase==='retreat'||this.phase==='clear'){
     if(cart.exitX===null)cart.exitX=cart.x;
     const p=clamp((this.time-(this.exitStart??Battle.RETREAT))/12,0,1);
     cart.x=cart.exitX+((cart.team?1.2:-.2)-cart.exitX)*p;continue;
    }
    if(cart.team)cart.x=1.2+(cart.dock-1.2)*clamp((this.time-cart.enterAt)/12,0,1);
    if(this.phase!=='battle'||(cart.team&&this.time<cart.enterAt+12)||this.time<cart.nextShot)continue;
    const targets=this.units.filter(u=>u.team!==cart.team&&u.deadAt===null&&!u.withdrawing);
    if(!targets.length)continue;
    const target=targets[Math.floor(this.random()*targets.length)];
    cart.shotAt=this.time;cart.nextShot=this.time+this.range(7,13);
    this.rocks.push({id:++this.rockId,team:cart.team,x:cart.x,y:cart.y,tx:target.x+this.range(-.018,.018),ty:clamp(target.y+this.range(-.025,.025),Battle.LAND,.95),at:this.time,duration:this.range(1.6,2.4),landed:false});
    if(this.rocks.length>12)this.rocks.shift();
   }
   for(const boat of this.boats){
    const arrival=clamp((this.time-boat.delay)/boat.duration,0,1);
    let progress=arrival*arrival*(3-2*arrival);
    const ahead=this.boats[boat.id-2];
    if(ahead&&ahead.progress<.9)progress=Math.min(progress,Math.max(0,ahead.progress-.10));
    boat.progress=progress;
    const entry=boat.entryX;
    const envelope=Math.sin(Math.PI*progress);
    const approach=clamp((progress-.55)/.45,0,1),fan=approach*approach*(3-2*approach);
    const channel=boat.id%2?.67:.40;
    boat.x=entry+(channel-entry)*progress+(boat.dock-channel)*fan+(boat.id%2?-.024:.024)*envelope+boat.bend*Math.sin(progress*Math.PI*2)*envelope;
    boat.y=.35+(boat.dockY-.35)*progress;boat.scale=.15+.48*progress;
    boat.heading=Math.sin(progress*Math.PI*2)*(boat.id%2?-3:3);
    boat.visible=this.phase!=='clear'&&this.time>=boat.delay;
    if(this.sailStart!==null){
     const away=clamp((this.time-this.sailStart-boat.id*.5)/18,0,1),p=away*away*(3-2*away);
     boat.x=boat.dock+(boat.entryX-boat.dock)*p;boat.y=boat.dockY+(-.12-boat.dockY)*p;
     boat.scale=.63+(.10-.63)*p;boat.heading=Math.sin(p*Math.PI)*(boat.entryX<boat.dock?-8:8);boat.visible=away<1;
    }
   }
   if(this.phase==='clear'){for(const u of this.units){u.state=u.deadAt===null?'offscreen':'fallen';u.x=u.team?1.25:-.25;}return;}
   for(const u of this.units){
    if(u.deadAt!==null)continue;
    if(u.capturedBy!=null)continue;
    if(u.civilian){
     this.panic(u,dt,width,height);
     continue;
    }
    if((this.returnStart!==null||u.captiveId!=null)&&u.team===1&&!u.withdrawing){this.returnToBoat(u,width,height);continue;}
    if(u.visitingHouse!==undefined&&u.visitingHouse!==null)continue;
    const landingBoat=u.boat===null?null:this.boats[u.boat];
    const landingEnd=landingBoat?landingBoat.landAt+Math.floor(Math.floor(u.id/2)/this.boats.length)*.18+1.2:0;
    // Village raiders pursue residents as soon as they step ashore.
    if(this.phase==='arrival'&&(!this.village||this.time<landingEnd)){
     const boat=u.boat===null?null:this.boats[u.boat];
     const disembarkAt=boat?boat.landAt+Math.floor(Math.floor(u.id/2)/this.boats.length)*.18:0;
     if(!boat){u.x=u.targetX;u.y=u.targetY;u.state='guarding';continue;}
     if(boat&&this.time<disembarkAt){
      u.x=boat.x+u.seatOffset*boat.scale/width;u.y=boat.y-18*boat.scale/height;u.state='sailing';continue;
     }
     const start=boat?disembarkAt:(u.id%6)*.35;
     if(boat&&this.time<start+1.2){
      const leap=clamp((this.time-start)/1.2,0,1),seat=u.seatOffset*boat.scale/width;
      u.x=boat.dock+seat;u.y=(boat.dockY-18*boat.scale/height)*(1-leap)+Battle.LAND*leap;
      u.jumpAt=start;u.jumpHeight=36;u.state='landing';continue;
     }
     const walkStart=boat?start+1.2:start;
     const progress=clamp((this.time-walkStart)/(this.arrivalEnd-1-walkStart),0,1);
     const fromX=boat?boat.dock+u.seatOffset*boat.scale/width:u.entryX;
     u.x=fromX+(u.targetX-fromX)*progress;
     u.y=Math.max(Battle.LAND,(boat?Battle.LAND*(1-progress)+u.targetY*progress:u.targetY)+Math.sin(progress*Math.PI)*u.bend);
     u.facing=u.targetX>(boat?boat.dock:u.entryX)?1:-1;
     u.state=progress===1?'guarding':'running';
     if(boat&&this.time-start<dt)u.jumpAt=this.time;
    }else if(this.phase==='raid'&&u.team===1&&!u.withdrawing){
     if(u.raidHouse===undefined){if(this.village)this.returnToBoat(u,width,height);else u.state='guarding';continue;}
     const house=this.settlement[u.raidHouse],age=this.time-this.raidStart-u.raidDelay;
     if(age<0){u.state='guarding';continue;}
     if(age<u.raidDuration){
      const p=clamp(age/u.raidDuration,0,1);u.x=u.raidFromX+(house.x-u.raidFromX)*p;u.y=u.raidFromY+(house.y-u.raidFromY)*p;
      u.facing=house.x<u.raidFromX?-1:1;u.state='running';
     }else if(age<u.raidDuration+2.2){
      u.x=house.x;u.y=house.y;u.state='inside';
      if(!u.raidSignaled){
       const peaceful=this.units.some(resident=>resident.civilian&&resident.deadAt===null&&resident.sheltered&&resident.houseId===house.id);
       this.signalHouse(house,this.time+5.5,peaceful?'hearts':null);u.raidSignaled=true;
      }
     }
     else{
      u.loot=true;
      if(this.village){this.returnToBoat(u,width,height);continue;}
      const p=clamp((age-u.raidDuration-2.2)/2,0,1);u.state=p<1?'running':'guarding';u.facing=1;u.x=house.x+.04*p;u.y=house.y+.012*p;
     }
     u.exitX=u.x;continue;
    }else if(this.phase==='retreat'){
     if(u.exitX===null)u.exitX=u.x;
     const p=clamp((this.time-(this.exitStart??Battle.RETREAT))/(this.exitStart===null?23:12),0,1);
     u.x=u.exitX+((u.team?1.2:-.2)-u.exitX)*p;u.facing=u.team?1:-1;u.state='running';
     this.bleed(u);
     continue;
    }else if(u.withdrawing){
     const age=this.time-u.withdrawAt;
     const progress=u.lostLeg?age/26+Math.sin(age*5)*.006:age/12;
     const p=clamp(progress,0,1);
     u.x=u.withdrawX+((u.team?1.2:-.2)-u.withdrawX)*p;u.facing=u.team?1:-1;u.state=p===1?'offscreen':'running';
     this.bleed(u);
     continue;
    }else{
     const enemies=this.units.filter(e=>e.team!==u.team&&e.deadAt===null&&!e.withdrawing&&!e.sheltered&&e.capturedBy==null&&e.state!=='offscreen'&&!(e.state==='hiding'&&this.settlement[e.houseId].encounter));
     let enemy=this.units[u.enemyId];
     const nearest=enemies.reduce((best,e)=>!best||Math.hypot((e.x-u.x)*width,(e.y-u.y)*height)<Math.hypot((best.x-u.x)*width,(best.y-u.y)*height)?e:best,null);
     if(nearest&&Math.hypot((nearest.x-u.x)*width,(nearest.y-u.y)*height)<75){
      enemy=nearest;u.enemyId=enemy.id;u.decisionAt=this.time+1;
     }
     if(this.time>=u.decisionAt||!enemy||!enemies.includes(enemy)){
      const partners=e=>this.units.filter(ally=>ally.team===u.team&&ally.id!==u.id&&ally.deadAt===null&&ally.enemyId===e.id).length;
      const distance=e=>Math.hypot((e.x-u.x)*width,(e.y-u.y)*height);
      const available=enemies.filter(e=>partners(e)<2);
      const ranked=(available.length?available:enemies).sort((a,b)=>distance(a)+partners(a)*30-distance(b)-partners(b)*30);
      const teamed=ranked.filter(e=>partners(e)===1&&distance(e)<180);
      // Sometimes assist a nearby ally; otherwise look for a separate duel.
      enemy=teamed.length&&this.random()<.35?teamed[0]:ranked[Math.min(ranked.length-1,this.random()<.18?1:0)];
      u.enemyId=enemy?.id;u.side=this.range(-16,16);u.decisionAt=this.time+this.range(1.3,3.8);
      if(enemy&&!enemy.civilian&&this.random()<.22){u.evadeUntil=this.time+this.range(.6,1.2);u.evadeSide=this.random()<.5?-1:1;if(this.random()<.3)u.jumpAt=this.time;}
     }
     if(!enemy){
      u.state='guarding';
      this.checkVictory();
      continue;
     }
     if(enemy.state==='hiding'){this.enterHouse(u,enemy,dt,width,height);continue;}
     const dx=(enemy.x-u.x)*width,dy=(enemy.y-u.y)*height;
     u.facing=dx<0?-1:1;
     const scale=(width<700?.7:.86)+(u.y-.7)*.65;
     const reach=(u.spearman?69:32)*scale,close=Math.abs(dx)<=reach+3&&Math.abs(dy)<13;
     const attacking=this.time-u.attackAt<u.attackDuration;
     if(u.archer&&!close){
      const distance=Math.hypot(dx,dy),preferred=Math.min(230,width*.32);
      if((!enemy.civilian&&distance<preferred*.72)||distance>preferred*1.3){
       const direction=distance<preferred?-1:1;
       this.move(u,dx*direction,dy*direction*.6,dt,width,height,u.speed*.75);
      }else u.state='aiming';
      if(distance>65&&distance<preferred*1.6&&this.time>=u.nextAttack){
       u.shotAt=this.time;u.nextAttack=this.time+this.range(2.5,4.8);
       this.arrows.push({id:++this.arrowId,x:u.x,y:u.y,tx:enemy.x,ty:enemy.y,target:enemy.id,direction:u.facing,at:this.time,duration:clamp(distance/280,.45,1.4),landed:false});
       if(this.arrows.length>32)this.arrows.shift();
      }
      continue;
     }
     if(!enemy.civilian&&this.time<u.evadeUntil&&!attacking){
      this.move(u,-u.facing*17,u.evadeSide*20,dt,width,height,26);continue;
     }
     if(!close&&!attacking){
      const targetDX=enemy.civilian?u.facing*Math.max(0,Math.abs(dx)-reach):dx-u.facing*reach;
      const flankY=u.squad%2?.93:.69;
      let targetDY=enemy.civilian?dy:u.strategy==='flank'&&Math.abs(dx)>160?(flankY-u.y)*height:dy+(Math.abs(dx)>90?u.side:0);
      if(!enemy.civilian&&Math.abs(dx)>130&&u.strategy!=='flank'){
       const group=this.units.filter(ally=>ally.team===u.team&&ally.squad===u.squad&&ally.deadAt===null&&!ally.withdrawing);
       const leader=group.reduce((best,ally)=>!best||(u.team?ally.x<best.x:ally.x>best.x)?ally:best,null);
       if(leader){const formationY=clamp(leader.y+u.targetY-leader.targetY,Battle.LAND,.95);targetDY=targetDY*.3+(formationY-u.y)*height*.7;}
      }
      this.move(u,targetDX,targetDY,dt,width,height,u.speed*(u.strategy==='shieldwall'?.8:1));
     }else{
      u.state=close?'fighting':'guarding';
      if(close&&this.time>=u.nextAttack){
       const styles=u.spearman?['spear-thrust','spear-low']:['overhead','sweep','jab'];
       // Avoid repeating the same gesture twice in succession.
       const choices=styles.filter(style=>style!==u.attackStyle);
       u.attackStyle=choices[Math.floor(this.random()*choices.length)];
       u.attackDuration=this.range(u.attackStyle==='jab'?.30:.38,u.attackStyle==='overhead'?.64:.54);
       u.impactDelay=u.attackDuration*(u.attackStyle==='jab'?.35:.44);
       u.attackAt=this.time;u.struck=false;u.nextAttack=this.time+u.attackDuration+this.range(.12,.5);
      }
      if(!u.struck&&this.time-u.attackAt>=u.impactDelay){
       u.struck=true;
       // Resolve hits at axe impact rather than killing on a scripted timer.
       if(close&&this.random()<.32){
        if(this.village&&enemy.civilian&&u.captiveId==null&&this.units.filter(unit=>unit.capturedBy!=null).length<this.boats.length&&this.random()<.25)this.capture(u,enemy);
        else this.wound(enemy,u.facing,u.team===1&&!u.spearman);
       }
      }
     }
    }
    if(!this.village&&this.time>=u.nextJump){
     if(u.state==='running')u.jumpAt=this.time;
     u.nextJump=this.time+this.range(5,15);
    }
   }
   this.updateCaptives(dt,width,height);
   if(this.returnStart!==null&&this.sailStart===null&&this.units.filter(u=>u.team===1&&u.deadAt===null&&!u.withdrawing).every(u=>u.state==='aboard')){
    this.sailStart=this.time;this.departureEnd=this.time+18+(this.boats.length-1)*.5+1;
   }
  }
 }
 if(typeof module!=='undefined'&&module.exports)module.exports=Battle;
 else window.FjordBattleModel=Battle;
})();
