/* Five real time series, presented as a quarter-turn cube carousel. */
(() => {
 'use strict';
 const root=document.querySelector('#tracker-insights');
 if(!root)return;
 const metrics=[
  {key:'ratio',name:'Ratio',tab:'Ratio',color:'#79dfb7',scope:'account'},
  {key:'credited_uploaded',name:'Krediteret upload',tab:'Kredit · upload',color:'#80d8b9',scope:'account'},
  {key:'real_uploaded',name:'Reel upload',tab:'Reel upload',color:'#8ebcfa',scope:'seedbox'},
  {key:'credited_downloaded',name:'Krediteret download',tab:'Kredit · download',color:'#c1a5f2',scope:'account'},
  {key:'real_downloaded',name:'Reel download',tab:'Reel download',color:'#f1c48e',scope:'seedbox'}
 ];
 const format=(value,key)=>typeof value!=='number'||!Number.isFinite(value)?'—':key==='ratio'?value.toLocaleString('da-DK',{maximumFractionDigits:3}):trackerBytes(value);
 const svgNode=(tag,attrs={})=>{const el=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value] of Object.entries(attrs))el.setAttribute(key,value);return el;};
 let gradientId=0;
 class Insights {
  constructor(){
   this.index=0;this.data={account:[],seedbox:[]};this.accounts=[];this.timer=null;this.busy=false;this.hover=false;this.focus=false;this.visible=false;this.loaded=false;this.generation=0;
   this.viewport=root.querySelector('.insights-viewport');this.current=root.querySelector('.insights-current');this.next=root.querySelector('.insights-next');this.cube=root.querySelector('.insights-cube');this.select=root.querySelector('#insights-account');this.mode=root.querySelector('.insights-mode span');this.error=root.querySelector('.insights-error');
   this.motion=matchMedia('(prefers-reduced-motion: reduce)');
   this.tabs=metrics.map((metric,i)=>{const button=node('button','insights-tab',metric.tab);button.type='button';button.setAttribute('aria-pressed',String(i===0));button.onclick=()=>this.turn(i);root.querySelector('.insights-tabs').append(button);return button;});
   root.addEventListener('pointerenter',event=>{if(event.pointerType==='mouse'){this.hover=true;this.schedule();}});
   root.addEventListener('pointerleave',event=>{if(event.pointerType==='mouse'){this.hover=false;this.schedule();}});
   root.addEventListener('focusin',event=>{this.focus=event.target.matches(':focus-visible');this.schedule();});
   root.addEventListener('focusout',()=>queueMicrotask(()=>{this.focus=root.contains(document.activeElement)&&document.activeElement.matches(':focus-visible');this.schedule();}));
   root.addEventListener('keydown',()=>{this.focus=true;this.schedule();});
   root.addEventListener('pointerdown',()=>{this.focus=false;this.schedule();});
   document.addEventListener('visibilitychange',()=>this.schedule());this.motion.addEventListener('change',()=>{if(this.busy)this.finish();this.schedule();});
   this.observer=new IntersectionObserver(entries=>{this.visible=entries[0].isIntersecting;this.schedule();});this.observer.observe(root);
   this.resize=new ResizeObserver(()=>{if(this.busy)this.finish();root.style.setProperty('--insight-depth',Math.max(1,this.viewport.clientWidth/2)+'px');this.draw();});this.resize.observe(this.viewport);
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
   root.querySelector('#insights-account-details').replaceChildren(trackerDetails(account,['uploaded','downloaded','ratio']));
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
   const paused=this.hover||this.focus||document.hidden||!this.visible||root.hidden||this.motion.matches||!this.loaded||!this.error.hidden;
   root.dataset.paused=String(paused);this.mode.textContent=this.motion.matches?'Vælg en graf':this.hover||this.focus?'På pause':'Automatisk';
   if(!paused&&!this.busy)this.timer=setTimeout(()=>this.turn((this.index+1)%metrics.length),8000);
  }
  turn(index){
   if(this.busy||index===this.index)return;
   clearTimeout(this.timer);
   if(this.motion.matches){this.index=index;this.draw();this.schedule();return;}
   this.busy=true;this.next.replaceChildren(...this.face(metrics[index]));this.next.style.setProperty('--insight-color',metrics[index].color);
   let done=false;
   this.finish=()=>{
    if(done)return;done=true;clearTimeout(this.fallback);this.cube.removeEventListener('transitionend',onEnd);
    this.cube.classList.remove('is-turning');this.next.replaceChildren();this.index=index;this.busy=false;this.draw();this.schedule();
   };
   const onEnd=event=>{if(event.target===this.cube&&event.propertyName==='transform')this.finish();};
   this.cube.addEventListener('transitionend',onEnd);void this.cube.offsetWidth;this.cube.classList.add('is-turning');this.fallback=setTimeout(this.finish,1200);
  }
  draw(){
   if(this.busy)return;
   const metric=metrics[this.index];root.dataset.metric=metric.key;root.style.setProperty('--insight-color',metric.color);this.current.style.setProperty('--insight-color',metric.color);
   this.current.replaceChildren(...this.face(metric));this.tabs.forEach((tab,i)=>tab.setAttribute('aria-pressed',String(i===this.index)));
  }
  face(metric){
   const account=this.accounts.find(a=>a.id===this.select.value);
   const samples=[];
   for(const point of this.data[metric.scope]||[]){
    if(typeof point[metric.key]!=='number'||!Number.isFinite(point[metric.key])){continue;}
    samples.push(point);
   }
   const changes=[];let pendingGap=false;
   for(const point of samples){
    pendingGap ||= !!point.gap_before;
    if(!changes.length||point[metric.key]!==changes.at(-1)[metric.key]||point[metric.key+'_reset']){changes.push(pendingGap?{...point,gap_before:true}:point);pendingGap=false;}
   }
   samples.splice(0,samples.length,...changes.slice(-60));
   const last=samples.at(-1),first=samples[0];
   const summary=node('div','insights-summary');summary.append(node('span','insights-metric-name',metric.name));
   const current=last?.[metric.key]??(metric.scope==='account'?account?.stats?.[metric.key==='credited_uploaded'?'uploaded':metric.key==='credited_downloaded'?'downloaded':'ratio']:null);
   summary.append(node('strong','insights-value',format(current,metric.key)));
   const reset=samples.some(point=>point[metric.key+'_reset']);
   const delta=last&&first?last[metric.key]-first[metric.key]:null;
   summary.append(node('span','insights-change'+(delta<0?' is-negative':''),reset?'Tælleren er nulstillet':samples.length>1?(delta>0?'↗ +':delta<0?'↘ −':'→ ')+format(Math.abs(delta),metric.key):'Afventer flere målinger'));
   const source=metric.scope==='account'?(account?.name||'Trackerkonto')+' · hele kontoen':'Hele seedboxen · fysisk trafik';
   const measured=last?'\nSeneste ændring '+new Date(last.at*1000).toLocaleString('da-DK',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'';
   summary.append(node('p','insights-source',source+'\n'+(samples.length>1?'Udvikling siden første viste ændring.':'Afventer en ændring i værdien.')+measured));
   const chart=node('div','insights-chart');
   if(!samples.length){const empty=node('div','insights-empty');empty.append(node('span','','⌁'),node('strong','',!this.loaded?'Henter din historik…':!this.error.hidden?'Historik midlertidigt utilgængelig':'Din historik starter her'),node('p','',!this.loaded?'Et øjeblik.':!this.error.hidden?'Vi prøver igen automatisk.':'Grafen starter ved den første måling. Tidligere aktivitet bliver ikke gættet.'));chart.append(empty);}
   else chart.append(this.plot(metric,samples));
   return [summary,chart];
  }
  plot(metric,points){
   const width=Math.max(220,this.viewport.clientWidth-(innerWidth<=650?32:48)),height=200,left=8,top=30,bottom=155;
   points=points.slice(-60).map((point,index)=>({...point,index}));
   const values=points.map(point=>point[metric.key]);
   const minimum=values.length?Math.min(...values):0,maximum=values.length?Math.max(...values):0;
   // Zoom to the observed totals, with breathing room and a stable flat-series range.
   const span=maximum-minimum;
   const padding=Math.max(span?span*.15:Math.max(maximum*.001,metric.key==='ratio'?.001:1),Number.EPSILON*Math.max(maximum,1)*8);
   const low=Math.max(0,minimum-padding),high=maximum+padding;
   const units=['B','KiB','MiB','GiB','TiB'];
   const unit=metric.key==='ratio'?0:Math.min(4,Math.max(0,Math.floor(Math.log2(Math.max(high,1))/10)));
   const divisor=metric.key==='ratio'?1:1024**unit;
   const digits=Math.min(12,Math.max(unit?2:0,Math.ceil(-Math.log10((high-low)/2/divisor))+1));
   const valueLabel=value=>(value/divisor).toLocaleString('da-DK',{minimumFractionDigits:digits,maximumFractionDigits:digits})+(metric.key==='ratio'?'':' '+units[unit]);
   const tickValues=[high,(high+low)/2,low];
   const right=width-Math.max(82,...tickValues.map(value=>valueLabel(value).length*6+14));
   const spacing=(right-left)/59;
   const x=point=>right-(points.length-1-point.index)*spacing,y=point=>bottom-(point[metric.key]-low)/(high-low)*(bottom-top);
   const svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,class:'insights-svg',role:'img',tabindex:'0','aria-label':metric.name+'. Op til 60 registrerede ændringer, nyeste til højre. Brug piletaster for at se værdi, dato og klokkeslæt.'});
   const axis=svgNode('text',{x:left,y:13,class:'insights-axis-title'});axis.textContent=(metric.key==='ratio'?'Ratio':'Samlet datamængde')+' · automatisk skala';svg.append(axis);
   const timeAxis=svgNode('text',{x:(left+right)/2,y:197,'text-anchor':'middle',class:'insights-axis-title'});timeAxis.textContent='Seneste 60 ændringer';svg.append(timeAxis);
   const id='insight-gradient-'+(++gradientId),defs=svgNode('defs'),gradient=svgNode('linearGradient',{id,x1:'0',y1:'0',x2:'0',y2:'1'});
   gradient.append(svgNode('stop',{offset:'0%','stop-color':metric.color,'stop-opacity':'.22'}),svgNode('stop',{offset:'100%','stop-color':metric.color,'stop-opacity':'0'}));defs.append(gradient);svg.append(defs);
   for(const fraction of [0,.5,1]){const py=top+fraction*(bottom-top),label=svgNode('text',{x:right+8,y:py+4,class:'insights-y-tick'});label.textContent=valueLabel(high-fraction*(high-low));svg.append(svgNode('line',{x1:left,x2:right,y1:py,y2:py,class:'insights-grid'}),label);}
   const zero=bottom;svg.append(svgNode('line',{x1:left,x2:right,y1:zero,y2:zero,class:'insights-zero'}));
   if(!points.length)return svg;
   let segment=[];
   const flush=()=>{if(!segment.length)return;const path=segment.map((p,i)=>(i?'L':'M')+x(p).toFixed(2)+','+y(p).toFixed(2)).join(' ');svg.append(svgNode('path',{d:path+` L${x(segment.at(-1))},${zero} L${x(segment[0])},${zero} Z`,fill:`url(#${id})`}),svgNode('path',{d:path,class:'insights-line'}));segment=[];};
   for(let i=0;i<points.length;i++){const p=points[i];if(i&&(p.gap_before||p[metric.key+'_reset']))flush();segment.push(p);}flush();
   const last=points.at(-1);svg.append(svgNode('circle',{cx:x(last),cy:y(last),r:4,class:'insights-point'}));
   for(const [text,px,anchor] of [['Ældre ændringer',left,'start'],['Nyeste',right,'end']]){const label=svgNode('text',{x:px,y:177,'text-anchor':anchor});label.textContent=text;svg.append(label);}
   const cursor=svgNode('line',{y1:top,y2:bottom,stroke:metric.color,'stroke-opacity':'.4',hidden:''}),tip=svgNode('text',{x:left+4,y:25,hidden:''});svg.append(cursor,tip);
   let selected=points.length-1;
   const show=index=>{selected=index;const point=points[index];cursor.removeAttribute('hidden');tip.removeAttribute('hidden');cursor.setAttribute('x1',x(point));cursor.setAttribute('x2',x(point));tip.textContent=new Date(point.at*1000).toLocaleString('da-DK',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})+' · '+valueLabel(point[metric.key]);};
   svg.addEventListener('pointermove',event=>{const box=svg.getBoundingClientRect(),px=(event.clientX-box.left)/box.width*width;let nearest=0;for(let i=1;i<points.length;i++)if(Math.abs(x(points[i])-px)<Math.abs(x(points[nearest])-px))nearest=i;show(nearest);});
   const hide=()=>{cursor.setAttribute('hidden','');tip.setAttribute('hidden','');};svg.addEventListener('pointerleave',hide);svg.addEventListener('blur',hide);svg.addEventListener('focus',()=>show(points.length-1));
   svg.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();show(Math.max(0,Math.min(points.length-1,selected+(event.key==='ArrowLeft'?-1:1))));}});
   return svg;
  }
 }
 window.trackerInsights=new Insights();
})();
