/* Five minutes of visible, unpaused time. Coordinates are feet on the ground. */
(() => {
 'use strict';
 const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
 class Battle {
  static DURATION=300;
  static RETREAT=270;
  static CLEAR=296;
  constructor(count=24,random=Math.random){this.count=count;this.random=random;this.round=0;this.reset();}
  range(a,b){return a+(b-a)*this.random();}
  reset(){
   this.time=0;this.round++;this.effects=[];this.effectId=0;
   this.boats=[0,1].map(team=>({team,x:team?1.3:-.3,y:.76+team*.13,dock:team?.83:.17,landAt:8+team*2}));
   this.units=Array.from({length:this.count},(_,id)=>{
    const team=id%2,lane=Math.floor(id/2)%4,entryX=team?1.12+id*.006:-.12-id*.006;
    const boat=Math.floor(id/2)%4===0?team:null;
    return {id,team,lane,boat,x:entryX,y:this.range(.72,.94),entryX,
     targetX:this.range(.12,.88),targetY:this.range(.72,.94),bend:this.range(-.06,.06),
     speed:this.range(32,57),decisionAt:0,side:0,enemyId:null,
     facing:team?-1:1,state:'running',deadAt:null,exitX:null,
     jumpAt:-10,nextJump:this.range(4,12),jumpHeight:this.range(12,25),
     attackAt:-10,nextAttack:this.range(15,19),struck:true,hp:4,hitAt:-10};
   });
  }
  get phase(){return this.time<15?'arrival':this.time<Battle.RETREAT?'battle':this.time<Battle.CLEAR?'retreat':'clear';}
  blood(u,direction=1){
   this.effects.push({id:++this.effectId,x:u.x,y:u.y,at:this.time,direction,seed:this.random()});
   if(this.effects.length>40)this.effects.shift();
  }
  kill(id){
   const u=this.units[id];if(!u||u.deadAt!==null||this.phase==='clear')return false;
   u.deadAt=this.time;u.state='fallen';u.jumpAt=-10;this.blood(u,u.facing);return true;
  }
  advance(dt,width=1600,height=1000){
   if(!Number.isFinite(dt)||dt<=0)return;
   this.time+=dt;
   if(this.time>=Battle.DURATION){this.reset();return;}
   this.effects=this.effects.filter(e=>this.time-e.at<1.15);
   width=Math.max(320,width);height=Math.max(320,height);
   for(const boat of this.boats){
    const entry=boat.team?1.3:-.3,progress=clamp(this.time/(boat.landAt-1),0,1);
    boat.x=entry+(boat.dock-entry)*(1-(1-progress)**2);
    if(this.time>boat.landAt+3)boat.x=boat.dock+(entry-boat.dock)*clamp((this.time-boat.landAt-3)/10,0,1);
   }
   if(this.phase==='clear'){for(const u of this.units){u.state=u.deadAt===null?'offscreen':'fallen';u.x=u.team?1.25:-.25;}return;}
   for(const u of this.units){
    if(u.deadAt!==null)continue;
    if(this.phase==='arrival'){
     const boat=u.boat===null?null:this.boats[u.boat];
     if(boat&&this.time<boat.landAt){
      u.x=boat.x+(Math.floor(u.id/8)-1)*22/width;u.y=boat.y-.018;u.state='sailing';continue;
     }
     const start=boat?boat.landAt:(u.id%6)*.35;
     const progress=clamp((this.time-start)/(14-start),0,1);
     u.x=(boat?boat.dock:u.entryX)+(u.targetX-(boat?boat.dock:u.entryX))*progress;
     u.y=(boat?(boat.y-.018)*(1-progress)+u.targetY*progress:u.targetY)+Math.sin(progress*Math.PI)*u.bend;
     u.facing=u.targetX>(boat?boat.dock:u.entryX)?1:-1;
     u.state=progress===1?'guarding':'running';
     if(boat&&this.time-start<dt)u.jumpAt=this.time;
    }else if(this.phase==='retreat'){
     if(u.exitX===null)u.exitX=u.x;
     const p=clamp((this.time-Battle.RETREAT)/23,0,1);
     u.x=u.exitX+((u.team?1.2:-.2)-u.exitX)*p;u.facing=u.team?1:-1;u.state='running';
    }else{
     const enemies=this.units.filter(e=>e.team!==u.team&&e.deadAt===null);
     let enemy=this.units[u.enemyId];
     if(this.time>=u.decisionAt||!enemy||enemy.deadAt!==null){
      const score=e=>Math.hypot((e.x-u.x)*width,(e.y-u.y)*height)+this.units.filter(ally=>ally.id!==u.id&&ally.deadAt===null&&ally.enemyId===e.id).length*45;
      const ranked=enemies.sort((a,b)=>score(a)-score(b));
      enemy=ranked[Math.min(ranked.length-1,this.random()<.22?1:0)];
      u.enemyId=enemy?.id;u.side=this.range(-16,16);u.decisionAt=this.time+this.range(1.3,3.8);
      if(this.random()<.22){u.evadeUntil=this.time+this.range(.6,1.2);u.evadeSide=this.random()<.5?-1:1;if(this.random()<.3)u.jumpAt=this.time;}
     }
     if(!enemy){
      if(this.time>=u.nextPatrol||u.nextPatrol===undefined){u.targetX=this.range(.12,.88);u.targetY=this.range(.72,.94);u.nextPatrol=this.time+this.range(3,7);}
      const dx=(u.targetX-u.x)*width,dy=(u.targetY-u.y)*height,distance=Math.hypot(dx,dy)||1,step=Math.min(distance,dt*u.speed*.45);
      u.x+=dx/distance*step/width;u.y+=dy/distance*step/height;u.facing=dx<0?-1:1;u.state=distance>5?'running':'guarding';
      continue;
     }
     const dx=(enemy.x-u.x)*width,dy=(enemy.y-u.y)*height;
     u.facing=dx<0?-1:1;
     const scale=(width<700?.7:.86)+(u.y-.7)*.65;
     const reach=32*scale,close=Math.abs(dx)<=reach+3&&Math.abs(dy)<13;
     const attacking=this.time-u.attackAt<.8;
     if(this.time<u.evadeUntil&&!attacking){
      u.x=clamp(u.x-u.facing*dt*17/width,.04,.96);u.y=clamp(u.y+u.evadeSide*dt*20/height,.70,.95);u.state='running';continue;
     }
     if(!close&&!attacking){
      const targetDX=dx-u.facing*reach,targetDY=dy+(Math.abs(dx)>65?u.side:0);
      const distance=Math.hypot(targetDX,targetDY)||1,step=Math.min(distance,dt*u.speed);
      u.x+=targetDX/distance*step/width;u.y=clamp(u.y+targetDY/distance*step/height,.70,.95);
      u.state='running';
     }else{
      u.state=close?'fighting':'guarding';
      if(close&&this.time>=u.nextAttack){u.attackAt=this.time;u.struck=false;u.nextAttack=this.time+this.range(1.2,2.8);}
      if(!u.struck&&this.time-u.attackAt>=.34){
       u.struck=true;
       // Resolve hits at axe impact rather than killing on a scripted timer.
       if(close&&this.random()<.32){
        enemy.hitAt=this.time;this.blood(enemy,u.facing);enemy.hp--;
        if(enemy.hp<=0&&this.units.filter(e=>e.deadAt===null).length>this.count/3)this.kill(enemy.id);
        else enemy.hp=Math.max(1,enemy.hp);
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
