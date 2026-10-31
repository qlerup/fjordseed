/* Absolute time series with persistent metric selectors and animated transitions. */
(() => {
 'use strict';
 const root=document.querySelector('#tracker-insights');
 if(!root)return;
 const nordicColors=['#79efbd','#ff80b2','#8fd7ff','#c59bff','#ffd56d','#f3d667'];
 const metrics=[
  {key:'ratio',name:'Ratio',tab:'Ratio',color:'#79dfb7',scope:'account'},
  {key:'credited_uploaded',name:'Krediteret upload',tab:'Kredit · upload',color:'#f18fb8',scope:'account'},
  {key:'real_uploaded',name:'Reel upload',tab:'Reel upload',color:'#8ebcfa',scope:'seedbox'},
  {key:'credited_downloaded',name:'Krediteret download',tab:'Kredit · download',color:'#c1a5f2',scope:'account'},
  {key:'real_downloaded',name:'Reel download',tab:'Reel download',color:'#f1c48e',scope:'seedbox'},
  {key:'seedbonus',name:'Shards',tab:'Shards',color:'#e5d87a',scope:'account'}
 ].map((metric,index)=>{const original=metric.color;return {...metric,get color(){return document.documentElement.dataset.theme==='nordic'?nordicColors[index]:original;}};});
 const format=(value,key)=>typeof value!=='number'||!Number.isFinite(value)?'—':['ratio','seedbonus'].includes(key)?value.toLocaleString('da-DK',{maximumFractionDigits:key==='ratio'?3:2}):trackerBytes(value);
 const svgNode=(tag,attrs={})=>{const el=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attrs))el.setAttribute(key,value);return el;};
 let gradientId=0;
 // Monotone cubic interpolation rounds corners without inventing peaks or dips.
 const curvePath=points=>{
  if(!points.length)return '';
  const pair=p=>p.x.toFixed(2)+','+p.y.toFixed(2);
  let path='M'+pair(points[0]);
  if(points.length===2)return path+' L'+pair(points[1]);
  const bend=.45;
  const slopes=points.slice(1).map((p,i)=>(p.y-points[i].y)/Math.max(.000001,p.x-points[i].x));
  const tangent=i=>{
   if(i===0)return slopes[0];if(i===points.length-1)return slopes.at(-1);
   const a=slopes[i-1],b=slopes[i];
   return a*b<=0?0:Math.sign(a)*Math.min(Math.abs((a+b)/2),Math.min(Math.abs(a),Math.abs(b))/(2*bend));
  };
  for(let i=1;i<points.length;i++){
   const a=points[i-1],b=points[i],dx=(b.x-a.x)*bend;
   path+=' C'+pair({x:a.x+dx,y:a.y+dx*tangent(i-1)})+' '+pair({x:b.x-dx,y:b.y-dx*tangent(i)})+' '+pair(b);
  }
  return path;
 };
 class Insights {
  constructor(){
   this.index=0;this.data={account:[],seedbox:[]};this.accounts=[];this.timer=null;this.busy=false;this.hover=false;this.focus=false;this.visible=false;this.loaded=false;this.generation=0;
   this.viewport=root.querySelector('.insights-viewport');this.current=root.querySelector('.insights-current');this.next=root.querySelector('.insights-next');this.stage=root.querySelector('.insights-stage');this.select=root.querySelector('#insights-account');this.mode=root.querySelector('.insights-mode span');this.error=root.querySelector('.insights-error');
   this.motion=matchMedia('(prefers-reduced-motion: reduce)');
   document.addEventListener('fjordseed:appearance',()=>{if(this.busy)this.finish();else if(this.loaded)this.draw();});
   this.tabs=[...metrics,{key:'all',tab:'Alle'}].map((metric,i)=>{const button=node('button','insights-tab',metric.tab);button.type='button';button.setAttribute('aria-label',metric.tab);button.setAttribute('aria-pressed',String(i===0));button.onclick=()=>this.turn(i);root.querySelector('.insights-selectors').append(button);return button;});
   const allButton=this.tabs.at(-1);
   allButton.classList.add('insights-all-button');
   const allIcon=svgNode('svg',{viewBox:'0 0 20 20',width:20,height:20,'aria-hidden':'true'});
   for(const [d,color] of [['M3 14L7 10L11 12L17 5','#79dfb7'],['M3 9L7 12L11 7L17 10','#c1a5f2'],['M3 17H17','#8ebcfa']])allIcon.append(svgNode('path',{d,stroke:color,'stroke-width':1.6,fill:'none','stroke-linecap':'round','stroke-linejoin':'round'}));
   allButton.replaceChildren(allIcon,node('span','','Alle'));
   root.addEventListener('pointerenter',event=>{if(event.pointerType==='mouse'){this.hover=true;this.schedule();}});
   root.addEventListener('pointerleave',event=>{if(event.pointerType==='mouse'){this.hover=false;this.schedule();}});
   root.addEventListener('focusin',event=>{this.focus=event.target.matches(':focus-visible');this.schedule();});
   root.addEventListener('focusout',()=>queueMicrotask(()=>{this.focus=root.contains(document.activeElement)&&document.activeElement.matches(':focus-visible');this.schedule();}));
   root.addEventListener('keydown',()=>{this.focus=true;this.schedule();});
   root.addEventListener('pointerdown',()=>{this.focus=false;this.schedule();});
   document.addEventListener('visibilitychange',()=>this.schedule());this.motion.addEventListener('change',()=>{if(this.busy)this.finish();this.schedule();});
   this.observer=new IntersectionObserver(entries=>{this.visible=entries[0].isIntersecting;this.schedule();});this.observer.observe(root);
   this.resize=new ResizeObserver(()=>{if(this.busy)this.finish();this.draw();});this.resize.observe(this.viewport);
   this.select.onchange=()=>this.reload();
   this.draw();
  }
  update(accounts){
   const selected=this.select.value;
   this.accounts=accounts;root.hidden=!accounts.length;
   if(!accounts.length){this.generation++;this.controller?.abort();this.schedule();return;}
   if(this.select.options.length!==accounts.length||accounts.some((a,i)=>this.select.options[i]?.value!==a.id||this.select.options[i]?.textContent!==a.name)){
    this.select.replaceChildren(...accounts.map(account=>{const option=node('option','',account.name);option.value=account.id;return option;}));
    if(accounts.some(account=>account.id===selected))this.select.value=selected;
   }
   this.select.closest('.insights-account').hidden=accounts.length===1;
   const account=accounts.find(a=>a.id===this.select.value);
   this.identity(account);
   const signature=account.id+':'+account.updated_at;
   if(this.signature!==signature||!this.lastFetched||Date.now()-this.lastFetched>60000){this.signature=signature;this.reload();}
  }
  identity(account){
   if(!account)return;
   root.querySelector('#insights-title').textContent=account.name;
   root.querySelector('#insights-account-details').replaceChildren(trackerDetails(account,['uploaded','downloaded','ratio','seedbonus']));
   const status=account.status==='ok'?'Forbundet':account.status==='error'?'Forbindelsesfejl':'Henter data';
   root.querySelector('#insights-account-status').textContent=[account.username,status,account.status==='error'?account.error:null].filter(Boolean).join(' · ');
  }
  async reload(){
   const account=this.accounts.find(a=>a.id===this.select.value);
   this.identity(account);
   if(account)this.signature=account.id+':'+account.updated_at;
   this.controller?.abort();this.controller=new AbortController();const generation=++this.generation;
   if(this.busy)this.finish();
   this.loaded=false;this.data={account:[],seedbox:[]};this.error.hidden=true;this.draw();this.schedule();
   try{
    const response=await fetch('/api/trackers/'+encodeURIComponent(this.select.value)+'/history?mode=changes',{signal:this.controller.signal,credentials:'same-origin'});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'Historikken kunne ikke hentes.');
    if(generation!==this.generation)return;
    this.data=result;this.loaded=true;this.lastFetched=Date.now();this.draw();this.schedule();
   }catch(error){if(generation!==this.generation||error.name==='AbortError')return;this.loaded=true;this.error.textContent=error.message;this.error.hidden=false;this.draw();this.schedule();}
  }
  schedule(){
   clearTimeout(this.timer);this.timer=null;
   const paused=this.hover||this.focus||document.hidden||!this.visible||root.hidden||this.motion.matches||!this.loaded||!this.error.hidden||this.index===metrics.length;
   root.dataset.paused=String(paused);this.mode.textContent=this.motion.matches?'Vælg en graf':this.hover||this.focus?'På pause':'Automatisk';
   if(!paused&&!this.busy)this.timer=setTimeout(()=>this.turn((this.index+1)%metrics.length),8000);
  }
  turn(index){
   if(this.busy)this.finish();
   if(index===this.index)return;
   clearTimeout(this.timer);
   this.tabs.forEach((tab,i)=>tab.setAttribute('aria-pressed',String(i===index)));
   if(this.motion.matches){this.index=index;this.draw();this.schedule();return;}
   this.busy=true;this.next.replaceChildren(...this.face(metrics[index]));
   this.next.style.setProperty('--insight-color',metrics[index]?.color||'#c1a5f2');
   const morph=document.documentElement.dataset.theme==='nordic'?null:this.morphLine();
   let done=false;
   this.finish=()=>{
    if(done)return;done=true;clearTimeout(this.fallback);cancelAnimationFrame(this.morphFrame);
    this.stage.classList.remove('is-changing','is-morphing');this.next.replaceChildren();this.index=index;this.busy=false;this.draw();this.schedule();
   };
   void this.stage.offsetWidth;this.stage.classList.add('is-changing');
   if(morph){
    this.stage.classList.add('is-morphing');
    const start=performance.now();
    const frame=now=>{const t=Math.min(1,(now-start)/800);morph(t*t*(3-2*t));if(t<1)this.morphFrame=requestAnimationFrame(frame);else this.finish();};
    morph(0);this.morphFrame=requestAnimationFrame(frame);
   }
   this.fallback=setTimeout(this.finish,morph?1000:650);
  }
  morphLine(){
   const oldLines=this.current.querySelectorAll('.insights-line'),newLines=this.next.querySelectorAll('.insights-line');
   // Never bridge history gaps, resets, or the independent series in All.
   if(oldLines.length!==1||newLines.length!==1||this.current.querySelector('.insights-all')||this.next.querySelector('.insights-all'))return null;
   const oldLine=oldLines[0],line=newLines[0];
   const vertices=path=>path.insightPoints||[];
   const from=vertices(oldLine),to=vertices(line);if(!from.length||!to.length)return null;
   const fractions=[...new Set([0,1,...from.map((_,i)=>i/Math.max(1,from.length-1)),...to.map((_,i)=>i/Math.max(1,to.length-1))])].sort((a,b)=>a-b);
   const sample=(points,t)=>{const at=t*(points.length-1),i=Math.floor(at),a=points[i],b=points[Math.min(i+1,points.length-1)],f=at-i;return {x:a.x+(b.x-a.x)*f,y:a.y+(b.y-a.y)*f};};
   const convert=line.getScreenCTM().inverse().multiply(oldLine.getScreenCTM());
   const pairs=fractions.map(t=>({a:new DOMPoint(sample(from,t).x,sample(from,t).y).matrixTransform(convert),b:sample(to,t)}));
   const area=line.previousElementSibling,point=line.ownerSVGElement.querySelector('.insights-point');
   const colors=[getComputedStyle(oldLine).stroke,getComputedStyle(line).stroke].map(color=>color.match(/[\d.]+/g).slice(0,3).map(Number));
   return t=>{
    const positions=pairs.map(({a,b})=>({x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t}));
    const d=curvePath(positions),last=positions.at(-1);
    line.setAttribute('d',d);line.style.stroke='rgb('+colors[0].map((v,i)=>v+(colors[1][i]-v)*t).join(',')+')';
    if(area?.tagName==='path')area.setAttribute('d',d+` L${last.x},155 L${positions[0].x},155 Z`);
    if(point){point.setAttribute('cx',last.x);point.setAttribute('cy',last.y);point.style.fill=line.style.stroke;}
   };
  }
  draw(){
   if(this.busy)return;
   const metric=metrics[this.index];root.dataset.metric=metric?.key||'all';root.style.setProperty('--insight-color',metric?.color||'#c1a5f2');this.current.style.setProperty('--insight-color',metric?.color||'#c1a5f2');
   this.current.replaceChildren(...this.face(metric));
   this.tabs.forEach((tab,i)=>{
    tab.setAttribute('aria-pressed',String(i===this.index));
    if(i===metrics.length)return;
    const m=metrics[i],samples=this.samples(m),account=this.accounts.find(a=>a.id===this.select.value);
    const value=samples.at(-1)?.[m.key]??(m.scope==='account'?account?.stats?.[m.key.replace('credited_','')]:null);
    tab.style.setProperty('--insight-color',m.color);
    tab.replaceChildren(node('span','insights-metric-name',m.name),node('strong','insights-selector-value',format(value,m.key)));
    if(m.scope==='seedbox')tab.append(node('small','','Seedbox'));
   });
  }
  samples(metric){
   const changes=[];let pendingGap=false;
   for(const point of this.data[metric.scope]||[]){
    if(!Number.isFinite(point[metric.key]))continue;
    pendingGap ||= !!point.gap_before;
    if(!changes.length||point[metric.key]!==changes.at(-1)[metric.key]||point[metric.key+'_reset']){changes.push(pendingGap?{...point,gap_before:true}:point);pendingGap=false;}
   }
   return changes.slice(-60);
  }
  face(metric){
   if(!metric)return this.allFace();
   const samples=this.samples(metric);
   const last=samples.at(-1),first=samples[0];
   const summary=node('div','insights-summary');

   const reset=samples.some(point=>point[metric.key+'_reset']);
   const delta=last&&first?last[metric.key]-first[metric.key]:null;
   summary.append(node('span','insights-change'+(delta<0?' is-negative':''),reset?'Tælleren er nulstillet':samples.length>1?(delta>0?'↗ +':delta<0?'↘ −':'→ ')+format(Math.abs(delta),metric.key):'Afventer flere målinger'));
   const measured=last?'\nSeneste ændring '+new Date(last.at*1000).toLocaleString('da-DK',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'';
   summary.append(node('p','insights-source',((samples.length>1?'':'Afventer en ændring i værdien.')+measured).trim()));
   const chart=node('div','insights-chart');
   if(!samples.length){const empty=node('div','insights-empty');empty.append(node('span','','⌁'),node('strong','',!this.loaded?'Henter din historik…':!this.error.hidden?'Historik midlertidigt utilgængelig':'Din historik starter her'),node('p','',!this.loaded?'Et øjeblik.':!this.error.hidden?'Vi prøver igen automatisk.':'Grafen starter ved den første måling. Tidligere aktivitet bliver ikke gættet.'));chart.append(empty);}
   else chart.append(this.plot(metric,samples));
   return [summary,chart];
  }
  allFace(){
   const series=metrics.map(metric=>({metric,points:this.samples(metric)}));
   const times=[...new Set(series.flatMap(s=>s.points.map(p=>p.at)))].sort((a,b)=>a-b).slice(-60);
   if(!times.length)return this.face(metrics[0]);
   const chart=node('div','insights-chart insights-all-chart');
   const legend=node('div','insights-ranges');
   for(const {metric,points} of series){
    const visible=points.filter(p=>p.at>=times[0]);
    if(!visible.length)continue;
    const svg=this.plot(metric,visible,times);svg.style.setProperty('--insight-color',metric.color);
    const range=node('span','',metric.name+': '+svg.dataset.range);range.style.color=metric.color;legend.append(range);
    if(chart.children.length)svg.querySelectorAll('text,.insights-grid,.insights-zero').forEach(el=>el.remove());
    else{svg.querySelectorAll('.insights-y-tick').forEach(el=>el.remove());svg.querySelector('.insights-axis-title').textContent='';}
    const dash=['','9 4','3 4','12 4 2 4','5 3','2 3 7 3'][metrics.indexOf(metric)];
    svg.querySelectorAll('.insights-line').forEach(el=>el.setAttribute('stroke-dasharray',dash));
    // Retain accessible per-series values while the shared plot provides pointer inspection.
    svg.removeAttribute('tabindex');svg.setAttribute('aria-label',metric.name);
    chart.append(svg);
   }
   const note=node('p','insights-source','Hver kurve har sin egen automatiske skala. Reel trafik: hele seedboxen.');
   const inspector=node('div','insights-all-inspector');inspector.setAttribute('aria-live','polite');
   chart.tabIndex=0;chart.setAttribute('role','group');chart.setAttribute('aria-label','Alle grafer. Brug piletaster til at se dato og totaler.');
   let selected=times.length-1;
   const show=index=>{
    selected=index;const at=times[index];inspector.replaceChildren(node('strong','',new Date(at*1000).toLocaleString('da-DK')));
    for(const {metric,points} of series){const point=points.find(p=>p.at===at);if(point){const item=node('span','',metric.name+': '+format(point[metric.key],metric.key));item.style.color=metric.color;inspector.append(item);}}
   };
   chart.addEventListener('pointermove',event=>{const box=chart.getBoundingClientRect();show(Math.max(0,Math.min(times.length-1,Math.round((event.clientX-box.left-8)/(box.width-32)*59)-(60-times.length))));});
   chart.addEventListener('focus',()=>show(selected));chart.addEventListener('pointerleave',()=>inspector.replaceChildren());chart.addEventListener('blur',()=>inspector.replaceChildren());
   chart.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();show(Math.max(0,Math.min(times.length-1,selected+(event.key==='ArrowLeft'?-1:1))));}});
   const body=node('div','insights-all');body.append(note,legend,chart,inspector);
   return [body];
  }
  plot(metric,points,times=null){
   const width=Math.max(220,this.viewport.clientWidth-(innerWidth<=650?32:48)),height=200,left=8,top=30,bottom=155;
   points=points.slice(-60).map((point,index)=>({...point,index}));
   const values=points.map(point=>point[metric.key]);
   const minimum=values.length?Math.min(...values):0,maximum=values.length?Math.max(...values):0;
   // Zoom to the observed totals, with breathing room and a stable flat-series range.
   const span=maximum-minimum;
   const padding=Math.max(span?span*.15:Math.max(maximum*.001,metric.key==='ratio'?.001:1),Number.EPSILON*Math.max(maximum,1)*8);
   const low=Math.max(0,minimum-padding),high=maximum+padding;
   const units=['B','KiB','MiB','GiB','TiB'];
   const numeric=['ratio','seedbonus'].includes(metric.key);
   const unit=numeric?0:Math.min(4,Math.max(0,Math.floor(Math.log2(Math.max(high,1))/10)));
   const divisor=numeric?1:1024**unit;
   const digits=Math.min(12,Math.max(unit?2:0,Math.ceil(-Math.log10((high-low)/2/divisor))+1));
   const valueLabel=value=>(value/divisor).toLocaleString('da-DK',{minimumFractionDigits:digits,maximumFractionDigits:digits})+(numeric?'':' '+units[unit]);
   const tickValues=[high,(high+low)/2,low];
   const right=times?width-24:width-Math.max(82,...tickValues.map(value=>valueLabel(value).length*6+14));
   const spacing=(right-left)/59;
   const x=point=>right-(times?times.length-1-times.indexOf(point.at):points.length-1-point.index)*spacing,y=point=>bottom-(point[metric.key]-low)/(high-low)*(bottom-top);
   const svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,class:'insights-svg',role:'img',tabindex:'0','aria-label':metric.name+'. Op til 60 registrerede ændringer, nyeste til højre. Brug piletaster for at se værdi, dato og klokkeslæt.'});
   svg.dataset.range=valueLabel(low)+' \u2013 '+valueLabel(high);
   const axis=svgNode('text',{x:left,y:13,class:'insights-axis-title'});axis.textContent=(metric.key==='ratio'?'Ratio':metric.key==='seedbonus'?'Shards':'Samlet datamængde')+' · automatisk skala';svg.append(axis);
   const timeAxis=svgNode('text',{x:(left+right)/2,y:197,'text-anchor':'middle',class:'insights-axis-title'});timeAxis.textContent='Seneste 60 ændringer';svg.append(timeAxis);
   const id='insight-gradient-'+(++gradientId),defs=svgNode('defs'),gradient=svgNode('linearGradient',{id,x1:'0',y1:'0',x2:'0',y2:'1'});
   gradient.append(svgNode('stop',{offset:'0%','stop-color':metric.color,'stop-opacity':'.22'}),svgNode('stop',{offset:'100%','stop-color':metric.color,'stop-opacity':'0'}));defs.append(gradient);svg.append(defs);
   for(const fraction of [0,.5,1]){const py=top+fraction*(bottom-top),label=svgNode('text',{x:right+8,y:py+4,class:'insights-y-tick'});label.textContent=valueLabel(high-fraction*(high-low));svg.append(svgNode('line',{x1:left,x2:right,y1:py,y2:py,class:'insights-grid'}),label);}
   const zero=bottom;svg.append(svgNode('line',{x1:left,x2:right,y1:zero,y2:zero,class:'insights-zero'}));
   if(!points.length)return svg;
   let segment=[];
   const flush=()=>{if(!segment.length)return;const positions=segment.map(p=>({x:x(p),y:y(p)})),path=curvePath(positions),line=svgNode('path',{d:path,class:'insights-line'});line.insightPoints=positions;svg.append(svgNode('path',{d:path+` L${x(segment.at(-1))},${zero} L${x(segment[0])},${zero} Z`,fill:`url(#${id})`}),line);segment=[];};
   for(let i=0;i<points.length;i++){const p=points[i];if(i&&(p.gap_before||p[metric.key+'_reset']))flush();segment.push(p);}flush();
   const last=points.at(-1);svg.append(svgNode('circle',{cx:x(last),cy:y(last),r:4,class:'insights-point'}));
   for(const [text,px,anchor] of [['Ældre ændringer',left,'start'],['Nyeste',right,'end']]){const label=svgNode('text',{x:px,y:177,'text-anchor':anchor});label.textContent=text;svg.append(label);}
   const cursor=svgNode('line',{y1:top,y2:bottom,stroke:metric.color,'stroke-opacity':'.4',hidden:''});
   const tip=svgNode('g',{class:'insights-tooltip',role:'tooltip',hidden:''});
   const bubble=svgNode('rect',{rx:6,height:38}),valueText=svgNode('text',{y:15,'text-anchor':'middle',class:'insights-tooltip-value'}),dateText=svgNode('text',{y:29,'text-anchor':'middle',class:'insights-tooltip-date'});
   tip.append(bubble,valueText,dateText);
   const marker=svgNode('circle',{r:4,class:'insights-point insights-hover-point',hidden:''});
   svg.append(cursor,marker,tip);
   let selected=points.length-1;
   const show=index=>{
    selected=index;const point=points[index],px=x(point),py=y(point);
    cursor.removeAttribute('hidden');tip.removeAttribute('hidden');marker.removeAttribute('hidden');
    cursor.setAttribute('x1',px);cursor.setAttribute('x2',px);marker.setAttribute('cx',px);marker.setAttribute('cy',py);
    valueText.textContent=numeric?point[metric.key].toLocaleString('da-DK',{maximumFractionDigits:metric.key==='ratio'?6:2}):valueLabel(point[metric.key]);
    dateText.textContent=new Date(point.at*1000).toLocaleString('da-DK',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'});
    const boxWidth=Math.min(width-8,Math.max(valueText.getComputedTextLength(),dateText.getComputedTextLength())+20);
    bubble.setAttribute('width',boxWidth);valueText.setAttribute('x',boxWidth/2);dateText.setAttribute('x',boxWidth/2);
    tip.setAttribute('transform',`translate(${Math.max(4,Math.min(width-boxWidth-4,px-boxWidth/2))},${Math.max(0,py-48)})`);
   };
   svg.addEventListener('pointermove',event=>{const box=svg.getBoundingClientRect(),px=(event.clientX-box.left)/box.width*width;let nearest=0;for(let i=1;i<points.length;i++)if(Math.abs(x(points[i])-px)<Math.abs(x(points[nearest])-px))nearest=i;show(nearest);});
   const hide=()=>{cursor.setAttribute('hidden','');tip.setAttribute('hidden','');marker.setAttribute('hidden','');};svg.addEventListener('pointerleave',hide);svg.addEventListener('blur',hide);svg.addEventListener('focus',()=>show(points.length-1));
   svg.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();show(Math.max(0,Math.min(points.length-1,selected+(event.key==='ArrowLeft'?-1:1))));}});
   return svg;
  }
 }
 window.trackerInsights=new Insights();
})();
