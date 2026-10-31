/* Five minutes of visible, unpaused time. No network, timers or app state. */
(() => {
 'use strict';
 class Battle {
  static DURATION=300;
  static RETREAT=270;
  static CLEAR=296;
  constructor(count=24){this.count=count;this.round=0;this.reset();}
  reset(){
   this.time=0;this.round++;this.casualty=0;
   this.units=Array.from({length:this.count},(_,id)=>{
    const team=id%2,lane=Math.floor(id/2)%4;
    return {id,team,lane,x:team?1.12+id*.006:-.12-id*.006,y:.70+lane*.068,
     entryX:team?1.12+id*.006:-.12-id*.006,
     targetX:.13+(Math.floor(id/2)/Math.max(1,this.count/2-1))*.74+(team?.022:-.022),
     facing:team?-1:1,state:'running',deadAt:null,exitX:null};
   });
  }
  get phase(){return this.time<15?'arrival':this.time<Battle.RETREAT?'battle':this.time<Battle.CLEAR?'retreat':'clear';}
  kill(id){const unit=this.units[id];if(!unit||unit.deadAt!==null||this.phase==='clear')return false;unit.deadAt=this.time;unit.state='fallen';return true;}
  advance(dt,width=1600){
   if(!Number.isFinite(dt)||dt<=0)return;
   this.time+=dt;
   if(this.time>=Battle.DURATION){this.reset();return;}
   if(this.phase==='clear'){for(const u of this.units){u.state=u.deadAt===null?'offscreen':'fallen';u.x=u.team?1.25:-.25;}return;}
   // One scripted defeat per duel, spread through the battle; the others survive.
   const due=Math.min(this.count/2,Math.max(0,Math.floor((this.time-38)/17)+1));
   while(this.casualty<due&&this.phase==='battle'){
    const pair=this.casualty++,id=pair*2+pair%2;
    this.kill(id);
   }
   for(const u of this.units){
    if(u.deadAt!==null)continue;
    if(this.phase==='arrival'){
     const progress=Math.max(0,Math.min(1,(this.time-(u.id%6)*.65)/11));
     u.x=u.entryX+(u.targetX-u.entryX)*progress;u.state=progress===1?'fighting':'running';
    }else if(this.phase==='retreat'){
     if(u.exitX===null)u.exitX=u.x;
     const p=Math.min(1,(this.time-Battle.RETREAT)/23);
     u.x=u.exitX+((u.team?1.2:-.2)-u.exitX)*p;u.facing=u.team?1:-1;u.state='running';
    }else{
     const enemies=this.units.filter(e=>e.team!==u.team&&e.deadAt===null);
     const enemy=enemies.sort((a,b)=>Math.abs(a.x-u.x)+Math.abs(a.y-u.y)*2-Math.abs(b.x-u.x)-Math.abs(b.y-u.y)*2)[0];
     if(!enemy){u.state='guarding';continue;}
     const dx=enemy.x-u.x,dy=enemy.y-u.y;
     u.facing=dx<0?-1:1;
     const gap=Math.min(.15,43/Math.max(320,width));
     const moving=Math.abs(dx)>gap||Math.abs(dy)>.014;
     if(moving){
      if(Math.abs(dx)>gap)u.x+=Math.sign(dx)*Math.min(Math.abs(dx)-gap,dt*.025);
      u.y+=Math.sign(dy)*Math.min(Math.abs(dy),dt*.012);
     }
     u.state=moving?'running':'fighting';
    }
   }
  }
 }
 if(typeof module!=='undefined'&&module.exports)module.exports=Battle;
 else window.FjordBattleModel=Battle;
})();
