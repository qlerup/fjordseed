/* Multi-file selection and bounded per-torrent previews use the existing APIs. */
(() => {
 'use strict';
 const input=$('#torrent-file'),zone=$('#torrent-dropzone'),dialog=$('#ratio-dialog');
 const MAX_FILES=50,MAX_BYTES=4*1024*1024,CONCURRENCY=3;
 let selected=[],items=[],reviewing=false,submitting=false,serial=0,packageOptions={};
 let selection=Promise.resolve(),selectionVersion=0,selectionJobs=0,context=null;
 const message=(selector,text)=>{$(selector).textContent=text;$(selector).hidden=!text;};
 const files=()=>selected.map(entry=>entry.file);
 function selectionView(){
  $('#torrent-selection-list').replaceChildren(...selected.map(entry=>{
   const li=node('li'),name=node('span','torrent-selection-name',entry.file.name);
   name.append(node('small','',size(entry.file.size)+' · torrentfil'));
   const remove=node('button','quiet','Fjern');remove.type='button';remove.setAttribute('aria-label','Fjern '+entry.file.name);
   remove.onclick=()=>{selected=selected.filter(item=>item!==entry);selectionView();};li.append(name,remove);return li;
  }));
  $('#torrent-selection-clear').hidden=!selected.length;
  $('#add-save').disabled=!current?.ready||(addMethod==='file'&&selectionJobs>0);
  $('#torrent-selection-status').textContent=selectionJobs?'Læser torrentfiler…':selected.length?`${selected.length} ${selected.length===1?'fil valgt':'filer valgt'} · ${size(selected.reduce((sum,e)=>sum+e.file.size,0))}`:'Ingen filer valgt';
  input.dataset.selectionState=selectionJobs?'loading':'ready';
 }
 function checksum(bytes){let hash=2166136261;for(const byte of bytes)hash=Math.imul(hash^byte,16777619);return hash>>>0;}
 function selectFiles(fileList){
  const incoming=[...fileList],version=selectionVersion;selectionJobs++;selectionView();
  selection=selection.then(async()=>{
   if(version!==selectionVersion)return;
   const notes=[];
   for(const file of incoming){
    if(version!==selectionVersion)return;
    if(!file.name.toLowerCase().endsWith('.torrent')){notes.push(`${file.name}: vælg en .torrent-fil.`);continue;}
    if(!file.size||file.size>MAX_BYTES){notes.push(`${file.name}: filen er tom eller større end 4 MB.`);continue;}
    if(selected.length>=MAX_FILES){notes.push('Du kan vælge højst 50 torrentfiler ad gangen.');break;}
    try{
     const bytes=new Uint8Array(await file.arrayBuffer()),hash=checksum(bytes);
     let duplicate=false;
     for(const existing of selected.filter(e=>e.file.size===file.size&&e.hash===hash)){
      const other=new Uint8Array(await existing.file.arrayBuffer());
      if(bytes.every((byte,i)=>byte===other[i])){duplicate=true;break;}
     }
     if(version!==selectionVersion)return;
     if(duplicate)notes.push(`${file.name}: filen er allerede valgt.`);
     else selected.push({file,hash});
    }catch(_){notes.push(`${file.name}: filen kunne ikke læses.`);}
   }
   if(version===selectionVersion)message('#torrent-selection-error',notes.slice(0,6).join(' ')+(notes.length>6?` Og ${notes.length-6} andre filer blev sprunget over.`:''));
  }).finally(()=>{if(version===selectionVersion){selectionJobs--;selectionView();}});
 }
 input.addEventListener('change',()=>{selectFiles(input.files);input.value='';});
 let dragDepth=0;
 zone.addEventListener('dragenter',e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();dragDepth++;zone.classList.add('is-dragging');}});
 zone.addEventListener('dragover',e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();e.dataTransfer.dropEffect='copy';}});
 zone.addEventListener('dragleave',()=>{if(--dragDepth<=0){dragDepth=0;zone.classList.remove('is-dragging');}});
 zone.addEventListener('drop',e=>{e.preventDefault();dragDepth=0;zone.classList.remove('is-dragging');selectFiles(e.dataTransfer.files);});
 for(const type of ['dragover','drop'])document.addEventListener(type,e=>{if($('#add-dialog').open&&e.dataTransfer?.types.includes('Files'))e.preventDefault();});
 $('#torrent-selection-clear').onclick=()=>{selectionVersion++;selectionJobs=0;selected=[];input.value='';message('#torrent-selection-error','');selectionView();};

 function stopPreviews(){
  if(!context)return;context.cancelled=true;clearTimeout(context.timer);
  for(const controller of context.requests)controller.abort();context=null;
 }
 function resetView(){
  stopPreviews();reviewing=false;items=[];packageOptions={};dialog.classList.remove('is-batch');
  $('#torrent-batch-review').hidden=true;$('#torrent-batch-list').replaceChildren();
  for(const id of ['single-benefit-tracker','preview-benefits','preview-ratio'])$('#'+id).hidden=false;
  $('#ratio-save').textContent='Start download';$('#ratio-save').disabled=false;
  $('#ratio-back').textContent='Tilbage';
 }
 function reset(){
  resetView();selectionVersion++;selectionJobs=0;selected=[];input.value='';selectionView();message('#torrent-selection-error','');
 }
 async function request(path,body,controller,timeout){
  const timer=setTimeout(()=>controller.abort(),timeout);
  try{
   const response=await fetch(path,{method:'POST',headers:{'X-CSRF-Token':csrf},body,signal:controller.signal});
   const result=await response.json().catch(()=>({error:'Serveren kunne ikke behandle filen.'}));
   if(!response.ok){const error=new Error(result.error||'Handlingen kunne ikke udføres.');error.status=response.status;throw error;}
   return result;
  }catch(error){
   if(error.name==='AbortError')throw new Error('Svaret tog for lang tid. Prøv igen.');
   throw error;
  }finally{clearTimeout(timer);}
 }
 function pendingItems(){return items.filter(item=>!item.removed&&!item.removing&&!item.added&&!item.invalid);}
 function summary(){
  if(!reviewing)return;
  const remaining=items.filter(item=>!item.removed),added=remaining.filter(item=>item.added).length;
  const pending=remaining.filter(item=>!item.added&&!item.invalid&&(!item.result||item.result.status==='pending'||item.result.ratio_estimates?.some(e=>e.status==='pending'))).length;
  $('#ratio-source').textContent=`${remaining.length} torrentfiler`;
  $('#torrent-batch-status').textContent=added?`${added} af ${remaining.length} tilføjet`:`${remaining.length} filer · ${pending?pending+' opslag i gang':'opslag færdige'}`;
  if(!submitting){
   const candidates=pendingItems();$('#ratio-save').disabled=!candidates.length;
   $('#ratio-save').textContent=candidates.some(item=>item.addError)?`Prøv ${candidates.length} igen`:`Start ${candidates.length} ${candidates.length===1?'download':'downloads'}`;
  }
 }
 function drawResult(item){
  const result=item.result||{status:'pending',message:'Venter på trackeropslag…'};
  item.benefits.replaceChildren(benefitView(result));renderRatioPreview(result,item.ratio);
  const estimates=result.ratio_estimates||[];
  item.ratioTitle.textContent=estimates.length?estimates.map(e=>e.status==='ok'?`${e.tracker_name}: forventet ratio ${e.infinite?'∞':Number(e.projected_ratio).toLocaleString('da-DK',{maximumFractionDigits:4})}`:`${e.tracker_name}: ratio ukendt`).join(' · '):result.status==='pending'?'Beregner forventet tracker-ratio…':'Forventet ratio er ukendt';
  item.state.textContent=item.added?'Tilføjet til downloads':item.addError|| (item.invalid?'Ugyldig torrentfil – fjern filen for at fortsætte.':size(item.file.size)+' · torrentfil');
  item.el.classList.toggle('is-added',!!item.added);item.el.classList.toggle('has-error',!!item.addError||item.invalid);
  item.retry.hidden=!!item.added;item.retry.disabled=submitting||!!item.controller;
  item.remove.disabled=submitting||!!item.added||!!item.removing;item.select.disabled=submitting||!!item.added||!!item.removing;
  summary();
 }
 function queue(item){
  if(item.added||item.removed||submitting)return;
  item.controller?.abort();item.version++;item.controller=null;item.result=null;item.invalid=false;item.attempts=0;item.started=0;item.nextAt=0;
  drawResult(item);if(!context&&dialog.open)context={requests:new Set(),cancelled:false,timer:0};pump(context);
 }
 function build(file){
  const item={file,id:++serial,version:0,nextAt:0,attempts:0,started:0,invalid:false,removed:false,added:false,controller:null};
  const el=node('article','torrent-batch-item');el.dataset.fileName=file.name;
  const head=node('div','batch-item-heading'),title=node('h4','',file.name),remove=node('button','quiet','Fjern');remove.type='button';remove.setAttribute('aria-label','Fjern '+file.name);head.append(title,remove);
  const state=node('p','batch-item-status');state.setAttribute('role','status');
  const label=node('label','','Tracker'),select=node('select');select.id=`batch-tracker-${item.id}`;select.setAttribute('aria-label','Tracker for '+file.name);
  const auto=node('option','','Find automatisk');auto.value='';select.append(auto);
  for(const tracker of typeof trackerData==='undefined'?[]:trackerData){const option=node('option','',tracker.name);option.value=tracker.id;select.append(option);}
  label.append(select);
  const benefits=node('div','batch-item-benefits'),detail=node('details','batch-ratio-detail'),ratioTitle=node('summary'),ratio=node('div');detail.append(ratioTitle,ratio);
  const retry=node('button','quiet batch-item-retry','Hent oplysninger igen');retry.type='button';
  el.append(head,state,label,benefits,detail,retry);
  Object.assign(item,{el,state,select,remove,benefits,ratio,ratioTitle,retry});
  select.onchange=()=>queue(item);retry.onclick=()=>queue(item);
  remove.onclick=async()=>{
   if(submitting)return;item.removing=true;remove.disabled=true;summary();
   try{
    if(packageOptions.remove)await packageOptions.remove(file);
    item.removed=true;item.controller?.abort();el.remove();selected=selected.filter(e=>e.file!==file);selectionView();summary();
   }catch(error){item.removing=false;if(items.includes(item)){message('#ratio-error',error.message);remove.disabled=false;summary();}}
  };
  return item;
 }
 function pump(ctx){
  if(!ctx||ctx!==context||ctx.cancelled||!dialog.open||submitting)return;
  clearTimeout(ctx.timer);
  const waiting=items.filter(item=>!item.removed&&!item.added&&!item.controller&&Number.isFinite(item.nextAt)).sort((a,b)=>a.nextAt-b.nextAt);
  while(ctx.requests.size<CONCURRENCY&&waiting.length&&waiting[0].nextAt<=Date.now()){
   const item=waiting.shift(),version=item.version,controller=new AbortController();
   ctx.requests.add(controller);item.controller=controller;item.retry.disabled=true;
   if(!item.started)item.started=Date.now();
   const body=new FormData();body.set('torrent',item.file);body.set('tracker_id',item.select.value);
   request('/api/torrents/preview',body,controller,20000).then(result=>{
    if(ctx!==context||ctx.cancelled||item.removed||item.version!==version)return;
    const pending=result.status==='pending'||result.ratio_estimates?.some(e=>e.status==='pending');
    item.result=pending&&Date.now()-item.started>180000?{status:'unknown',message:'Trackeropslaget er endnu ikke klart. Du kan hente oplysningerne igen.'}:result;
    item.nextAt=pending&&Date.now()-item.started<=180000?Date.now()+(++item.attempts<=4?750:2500):Infinity;
   }).catch(error=>{
    if(ctx!==context||ctx.cancelled||item.removed||item.version!==version)return;
    item.invalid=[400,413].includes(error.status);item.nextAt=Infinity;
    item.result={status:'unknown',message:error.message};
   }).finally(()=>{
    ctx.requests.delete(controller);
    if(item.controller===controller)item.controller=null;
    if(ctx===context&&!ctx.cancelled&&!item.removed&&item.version===version)drawResult(item);
    pump(ctx);
   });
  }
  if(waiting.length&&ctx.requests.size<CONCURRENCY)ctx.timer=setTimeout(()=>pump(ctx),Math.max(50,waiting[0].nextAt-Date.now()));
 }
 function open(fileList,options={}){
  resetView();packageOptions=options;reviewing=true;dialog.classList.add('is-batch');$('#torrent-batch-review').hidden=false;
  if(options.ids)$('#ratio-back').textContent='Luk pakken';
  for(const id of ['single-benefit-tracker','preview-benefits','preview-ratio'])$('#'+id).hidden=true;
  items=fileList.map(build);$('#torrent-batch-list').replaceChildren(...items.map(item=>item.el));
  items.forEach(drawResult);context={requests:new Set(),cancelled:false,timer:0};pump(context);
 }
 async function submit(){
  if(!reviewing||submitting)return;
  const batch=pendingItems();if(!batch.length)return;
  const policy={convert:String($('#ratio-convert').checked),ratio_limit:$('#ratio-limit').value,ratio_action:$('#ratio-action').value,seed_minutes:$('#ratio-seed-minutes').value};
  submitting=true;stopPreviews();message('#ratio-error','');
  const controls=[...$('#ratio-form').querySelectorAll('input,select,button')].map(el=>({el,disabled:el.disabled}));controls.forEach(({el})=>el.disabled=true);
  try{
   for(const [index,item] of batch.entries()){
    $('#ratio-save').textContent=`Tilføjer ${index+1} af ${batch.length}…`;item.state.textContent='Tilføjer torrent…';
    const body=new FormData();
    if(packageOptions.ids)body.set('package_item_id',packageOptions.ids.get(item.file));else body.set('torrent',item.file);
    for(const [key,value] of Object.entries(policy))body.set(key,value);
    try{
     await request('/api/torrents',body,new AbortController(),60000);
     item.added=true;item.addError='';selected=selected.filter(entry=>entry.file!==item.file);
     document.dispatchEvent(new Event('fjordseed:package-updated'));
    }catch(error){item.addStatus=error.status;item.addError=error.status?error.message:'Tilføjelsen kunne ikke bekræftes. Kontrollér Downloads før et nyt forsøg. '+error.message;}
    drawResult(item);
    if([401,403].includes(item.addStatus))break;
   }
   const remaining=items.filter(item=>!item.added&&!item.removed);
   if(!remaining.length){const count=items.filter(item=>item.added).length;dialog.close();toast(`${count} torrents tilføjet`);}
   else message('#ratio-error',`${items.filter(item=>item.added).length} torrents er tilføjet. ${remaining.length} mangler. Fjern ugyldige filer, eller prøv de resterende igen. Filer, der allerede er tilføjet, sendes ikke igen.`);
   selectionView();await refresh();
  }finally{
   submitting=false;controls.forEach(({el,disabled})=>el.disabled=disabled);items.filter(item=>!item.removed).forEach(drawResult);summary();
  }
 }
 dialog.addEventListener('close',stopPreviews);
 window.TorrentBatch={files,reset,resetView,open,submit,get packaged(){return !!packageOptions.ids;},get active(){return reviewing;},get submitting(){return submitting;},get selecting(){return selectionJobs>0;}};
})();
