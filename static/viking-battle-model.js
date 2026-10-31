/* Five minutes of visible, unpaused time. Coordinates are feet on the ground. */
(() => {
 'use strict';
 const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
 class Battle {
  static DURATION=300;
  static RETREAT=270;
  static CLEAR=296;
  static LAND=.66;
  constructor(count=64,random=Math.random){this.count=count;this.random=random;this.round=0;this.reset();}
  range(a,b){return a+(b-a)*this.random();}
  reset(){
   this.time=0;this.round++;this.effects=[];this.effectId=0;this.arrows=[];this.arrowId=0;
   this.exitStart=null;this.winner=null;this.trails=[];this.trailId=0;this.rocks=[];this.rockId=0;
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
   const fleetSize=5+Math.floor(this.random()*4);
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
   this.units=Array.from({length:this.count},(_,id)=>{
    const team=id%2,lane=Math.floor(id/2)%4,entryX=team?1.12+id*.006:-.12-id*.006;
    const boat=team===1?Math.floor(id/2)%fleetSize:null;
    const rank=Math.floor(id/2),squad=Math.floor(rank/8),slot=rank%8,archer=id%8<2;
    const strategy=this.formations[team][squad];
    const centerX=.17+(squad%2)*.19,centerY=.685+Math.floor(squad/2)*.14;
    const column=Math.floor(slot/4),front=strategy==='wedge'?-.018*Math.abs(lane-1.5):strategy==='flank'?.012*lane:0;
    const targetX=centerX+front-column*.03-(archer?.035:0)+this.range(-.004,.004);
    const targetY=centerY+lane*.032;
    const seats=boat===null?0:Math.ceil((this.count/2-boat)/fleetSize),seat=Math.floor(rank/fleetSize);
    return {id,team,lane,squad,boat,seatOffset:(seat-(seats-1)/2)*26,archer,spearman:!archer&&rank%3===1,strategy,
     x:team?this.boats[boat].x:targetX,y:team?.35:targetY,entryX,
     targetX:team?1-targetX:targetX,targetY,bend:this.range(-.015,.015),
     speed:this.range(32,57),decisionAt:0,side:0,enemyId:null,
     facing:team?-1:1,state:team?'sailing':'guarding',deadAt:null,exitX:null,
     jumpAt:-10,nextJump:this.range(4,12),jumpHeight:this.range(12,25),
     attackAt:-10,attackStyle:'overhead',attackDuration:.8,impactDelay:.34,nextAttack:this.range(15,19),struck:true,hp:3+Math.floor(this.random()*3),hitAt:-10};
   });
  }
  get phase(){
   if(this.exitStart!==null)return this.time<this.exitStart+12?'retreat':'clear';
   return this.time<this.arrivalEnd?'arrival':this.time<Battle.RETREAT?'battle':this.time<Battle.CLEAR?'retreat':'clear';
  }
  checkVictory(){
   if(this.phase!=='battle')return;
   const teams=new Set(this.units.filter(u=>u.deadAt===null&&!u.withdrawing&&u.state!=='offscreen').map(u=>u.team));
   if(teams.size>1)return;
   this.exitStart=this.time;this.winner=teams.size?[...teams][0]:null;this.arrows=[];this.rocks=[];
   const leader=this.units.find(u=>u.deadAt===null&&!u.withdrawing&&u.team===this.winner);
   for(const u of this.units){
    if(u.deadAt!==null)continue;
    u.exitX=u.x;u.enemyId=null;u.attackAt=-10;u.shotAt=-10;u.jumpAt=-10;u.nextJump=Infinity;
    u.facing=u.team?1:-1;u.state='running';u.flag=u===leader;
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
   else if(limb&&!u.withdrawing){
    u.withdrawing=true;u.withdrawAt=this.time;u.withdrawX=u.x;u.enemyId=null;u.attackAt=-10;u.shotAt=-10;u.nextJump=Infinity;u.state='running';u.facing=u.team?1:-1;
   }
   this.checkVictory();
  }
  kill(id){
   const u=this.units[id];if(!u||u.deadAt!==null||this.phase==='clear')return false;
   u.deadAt=this.time;u.state='fallen';u.jumpAt=-10;this.blood(u,u.facing);this.checkVictory();return true;
  }
  move(u,dx,dy,dt,width,height,speed=u.speed){
   const gait=u.lostLeg?.24+.22*Math.max(0,Math.sin(this.time*5+u.id)):1;
   const distance=Math.hypot(dx,dy)||1,step=Math.min(distance,dt*speed*gait);
   let nx=clamp(u.x+dx/distance*step/width,.025,.975),ny=clamp(u.y+dy/distance*step/height,Battle.LAND,.95);
   for(const other of this.units){
    if(other.id===u.id||other.deadAt!==null||other.withdrawing||other.state==='sailing')continue;
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
  advance(dt,width=1600,height=1000){
   if(!Number.isFinite(dt)||dt<=0)return;
   this.time+=dt;
   if(this.time>=(this.exitStart===null?Battle.DURATION:this.exitStart+13)){this.reset();return;}
   this.checkVictory();
   this.effects=this.effects.filter(e=>this.time-e.at<4);
   this.trails=this.trails.filter(e=>this.time-e.at<18);
   width=Math.max(320,width);height=Math.max(320,height);
   for(const arrow of this.arrows){
    if(!arrow.landed&&this.time-arrow.at>=arrow.duration){
     arrow.landed=true;const target=this.units[arrow.target];
     if(this.phase==='battle'&&target.deadAt===null&&Math.hypot((target.x-arrow.tx)*width,(target.y-arrow.ty)*height)<26&&this.random()<.55){
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
   }
   if(this.phase==='clear'){for(const u of this.units){u.state=u.deadAt===null?'offscreen':'fallen';u.x=u.team?1.25:-.25;}return;}
   for(const u of this.units){
    if(u.deadAt!==null)continue;
    if(this.phase==='arrival'){
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
     const enemies=this.units.filter(e=>e.team!==u.team&&e.deadAt===null&&!e.withdrawing&&e.state!=='offscreen');
     let enemy=this.units[u.enemyId];
     const nearest=enemies.reduce((best,e)=>!best||Math.hypot((e.x-u.x)*width,(e.y-u.y)*height)<Math.hypot((best.x-u.x)*width,(best.y-u.y)*height)?e:best,null);
     if(nearest&&Math.hypot((nearest.x-u.x)*width,(nearest.y-u.y)*height)<75){
      enemy=nearest;u.enemyId=enemy.id;u.decisionAt=this.time+1;
     }
     if(this.time>=u.decisionAt||!enemy||enemy.deadAt!==null||enemy.withdrawing){
      const partners=e=>this.units.filter(ally=>ally.team===u.team&&ally.id!==u.id&&ally.deadAt===null&&ally.enemyId===e.id).length;
      const distance=e=>Math.hypot((e.x-u.x)*width,(e.y-u.y)*height);
      const available=enemies.filter(e=>partners(e)<2);
      const ranked=(available.length?available:enemies).sort((a,b)=>distance(a)+partners(a)*30-distance(b)-partners(b)*30);
      const teamed=ranked.filter(e=>partners(e)===1&&distance(e)<180);
      // Sometimes assist a nearby ally; otherwise look for a separate duel.
      enemy=teamed.length&&this.random()<.35?teamed[0]:ranked[Math.min(ranked.length-1,this.random()<.18?1:0)];
      u.enemyId=enemy?.id;u.side=this.range(-16,16);u.decisionAt=this.time+this.range(1.3,3.8);
      if(this.random()<.22){u.evadeUntil=this.time+this.range(.6,1.2);u.evadeSide=this.random()<.5?-1:1;if(this.random()<.3)u.jumpAt=this.time;}
     }
     if(!enemy){
      this.checkVictory();
      continue;
     }
     const dx=(enemy.x-u.x)*width,dy=(enemy.y-u.y)*height;
     u.facing=dx<0?-1:1;
     const scale=(width<700?.7:.86)+(u.y-.7)*.65;
     const reach=(u.spearman?69:32)*scale,close=Math.abs(dx)<=reach+3&&Math.abs(dy)<13;
     const attacking=this.time-u.attackAt<u.attackDuration;
     if(u.archer&&!close){
      const distance=Math.hypot(dx,dy),preferred=Math.min(230,width*.32);
      if(distance<preferred*.72||distance>preferred*1.3){
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
     if(this.time<u.evadeUntil&&!attacking){
      this.move(u,-u.facing*17,u.evadeSide*20,dt,width,height,26);continue;
     }
     if(!close&&!attacking){
      const targetDX=dx-u.facing*reach;
      const flankY=u.squad%2?.93:.69;
      let targetDY=u.strategy==='flank'&&Math.abs(dx)>160?(flankY-u.y)*height:dy+(Math.abs(dx)>90?u.side:0);
      if(Math.abs(dx)>130&&u.strategy!=='flank'){
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
        this.wound(enemy,u.facing,!u.spearman);
       }
      }
     }
    }
    if(this.time>=u.nextJump){
     if(u.state==='running')u.jumpAt=this.time;
     u.nextJump=this.time+this.range(5,15);
    }
   }
  }
 }
 if(typeof module!=='undefined'&&module.exports)module.exports=Battle;
 else window.FjordBattleModel=Battle;
})();
