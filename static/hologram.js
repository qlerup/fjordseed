/* Local depth-tested hologram: no blur, external services or UI interaction. */
(async()=>{
 'use strict';
 const canvas=document.createElement('canvas');canvas.id='skull-hologram';canvas.setAttribute('aria-hidden','true');document.body.prepend(canvas);
 const gl=canvas.getContext('webgl',{alpha:true,antialias:true,premultipliedAlpha:false,preserveDrawingBuffer:true});
 if(!gl){canvas.remove();return;}
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');let mesh;
 try{const r=await fetch('/static/skull-mesh.json?v=2');if(!r.ok)throw Error();mesh=await r.json();}catch{canvas.remove();return;}
 function shader(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error('Hologram shader');return s;}
 let program;
 try{
  program=gl.createProgram();
  gl.attachShader(program,shader(gl.VERTEX_SHADER,`
   attribute vec3 position;attribute vec3 normal;
   uniform float angle;uniform vec2 viewport;uniform vec2 center;uniform float scale;
   varying vec3 surfaceNormal;
   void main(){
    float c=cos(angle),s=sin(angle);mat3 rotation=mat3(c,0.,-s,0.,1.,0.,s,0.,c);
    vec3 p=rotation*position;surfaceNormal=rotation*normal;float w=3.8-p.z;
    vec2 pixel=center+vec2(p.x,p.y)*scale*3.8/w;
    gl_Position=vec4((pixel.x/viewport.x*2.-1.)*w,(1.-pixel.y/viewport.y*2.)*w,-p.z*.65,w);
   }`));
  gl.attachShader(program,shader(gl.FRAGMENT_SHADER,`
   precision mediump float;varying vec3 surfaceNormal;uniform float pixelRatio;
   void main(){
    vec3 n=normalize(surfaceNormal);if(!gl_FrontFacing)n=-n;
    float light=max(0.,dot(n,normalize(vec3(-.5,-.7,1.))));
    float rim=pow(1.-abs(n.z),2.5);float scan=step(.82,fract(gl_FragCoord.y/(3.*pixelRatio)));
    float intensity=.12+light*.58+rim*.36;
    vec3 color=mix(vec3(.025,.19,.22),vec3(.27,.92,.84),intensity);
    color+=vec3(.1,.22,.21)*rim;color*=1.-scan*.24;
    gl_FragColor=vec4(color,.72+rim*.20);
   }`));
  gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error();
 }catch{canvas.remove();return;}
 gl.useProgram(program);
 function attribute(name,data){const b=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(data.flat()),gl.STATIC_DRAW);const a=gl.getAttribLocation(program,name);gl.enableVertexAttribArray(a);gl.vertexAttribPointer(a,3,gl.FLOAT,false,0,0);}
 attribute('position',mesh.vertices);attribute('normal',mesh.normals);
 const indices=gl.createBuffer();gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,indices);gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,new Uint16Array(mesh.triangles),gl.STATIC_DRAW);
 const uniforms=Object.fromEntries(['angle','viewport','center','scale','pixelRatio'].map(n=>[n,gl.getUniformLocation(program,n)]));
 gl.frontFace(gl.CW);gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.clearColor(0,0,0,0);
 let frame=0,last=0,angle=-.30,lost=false;
 function draw(){if(lost)return;gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.uniform1f(uniforms.angle,angle);gl.drawElements(gl.TRIANGLES,mesh.triangles.length,gl.UNSIGNED_SHORT,0);}
 function resize(){
  const width=innerWidth,height=innerHeight,dpr=Math.min(devicePixelRatio||1,3);
  canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);gl.viewport(0,0,canvas.width,canvas.height);
  gl.uniform2f(uniforms.viewport,width,height);gl.uniform2f(uniforms.center,width*(width<800?.62:.72),height*.51);
  gl.uniform1f(uniforms.scale,Math.min(height*.36,width<800?width*.48:width*.29));gl.uniform1f(uniforms.pixelRatio,dpr);draw();
 }
 function tick(now){frame=0;if(document.hidden||reduced.matches||lost)return;if(now-last>=1000/30){angle+=Math.min(now-last,100)/1000*Math.PI*2/80;last=now;draw();}frame=requestAnimationFrame(tick);}
 function resume(){cancelAnimationFrame(frame);frame=0;last=performance.now();if(!document.hidden&&!reduced.matches&&!lost)frame=requestAnimationFrame(tick);else draw();}
 canvas.addEventListener('webglcontextlost',()=>{lost=true;cancelAnimationFrame(frame);canvas.remove();});
 addEventListener('resize',resize,{passive:true});document.addEventListener('visibilitychange',resume);reduced.addEventListener('change',resume);
 resize();resume();
})();
