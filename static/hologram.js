/* Local 3D wire sculpture. No external requests or dependencies. */
(async () => {
 'use strict';
 const canvas=document.createElement('canvas');canvas.id='skull-hologram';
 canvas.setAttribute('aria-hidden','true');document.body.prepend(canvas);
 const ctx=canvas.getContext('2d');if(!ctx){canvas.remove();return;}
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 let mesh;
 try{const response=await fetch('/static/skull-mesh.json?v=1');if(!response.ok)throw new Error('mesh');mesh=await response.json();}
 catch{canvas.remove();return;}
 const dots=mesh.vertices;
 let width=0,height=0,frame=0,last=0,angle=-.30;
 function resize(){width=innerWidth;height=innerHeight;const dpr=Math.min(devicePixelRatio||1,1.5);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw();}
 function draw(){
  ctx.clearRect(0,0,width,height);
  const scale=Math.min(height*.39,width<800?width*.48:width*.29),cx=width<800?width*.62:width*.72,cy=height*.53;
  const c=Math.cos(angle),s=Math.sin(angle);
  function project(p){const x=p[0]*c+p[2]*s,z=p[2]*c-p[0]*s;const perspective=3.8/(3.8-z);return [cx+x*scale*perspective,cy+p[1]*scale*perspective,z];}
  const projected=dots.map(project),buckets=Array.from({length:12},()=>[]);
  for(const [a,b] of mesh.edges){const p=projected[a],q=projected[b];const bucket=Math.max(0,Math.min(11,Math.floor(((p[2]+q[2])*.5+1)*5.5)));buckets[bucket].push([p,q]);}
  ctx.lineWidth=.65;ctx.shadowColor='#48dfd0';ctx.shadowBlur=3;
  for(let i=0;i<buckets.length;i++){
   ctx.strokeStyle=`rgba(74,224,207,${.06+i*.034})`;ctx.beginPath();
   for(const [p,q] of buckets[i]){ctx.moveTo(p[0],p[1]);ctx.lineTo(q[0],q[1]);}
   ctx.stroke();
  }
  ctx.shadowBlur=0;ctx.fillStyle='rgba(156,255,241,.65)';
  for(let i=0;i<projected.length;i+=3){const p=projected[i];if(p[2]>0)ctx.fillRect(p[0],p[1],1.2,1.2);}
  // Fine scan lines are confined to the sculpture, not the interface.
  ctx.globalCompositeOperation='source-atop';ctx.fillStyle='rgba(8,18,25,.32)';
  for(let y=0;y<height;y+=4)ctx.fillRect(0,y,width,1);
  ctx.globalCompositeOperation='source-over';
 }
 function tick(now){frame=0;if(document.hidden||reduced.matches)return;
  if(now-last>=1000/24){angle+=(Math.min(now-last,100)/1000)*(Math.PI*2/80);last=now;draw();}
  frame=requestAnimationFrame(tick);
 }
 function resume(){cancelAnimationFrame(frame);frame=0;last=performance.now();if(!document.hidden&&!reduced.matches)frame=requestAnimationFrame(tick);else draw();}
 addEventListener('resize',resize,{passive:true});document.addEventListener('visibilitychange',resume);reduced.addEventListener('change',resume);
 resize();resume();
})();
