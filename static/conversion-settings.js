(() => {
 let last,renderedSignature;
 const folderOpen=new Set(),searches=new Map();
 const views=new Map(),bitrateCache=new Map(),bitrateBusy=new Set();
 const scope=d=>d.id+'\0'+d.media_folder;
 const fmt=n=>new Intl.NumberFormat('da-DK',{maximumFractionDigits:1}).format(n/1000000)+' Mbps';
 function updatePhaseTimes(){
  document.querySelectorAll('[data-phase-start]').forEach(el=>{
   const seconds=Math.max(0,Math.floor(Date.now()/1000-Number(el.dataset.phaseStart)));
   const minutes=Math.floor(seconds/60),hours=Math.floor(minutes/60);
   el.textContent='Tid på dette trin · '+(hours?hours+':'+String(minutes%60).padStart(2,'0'):minutes)+':'+String(seconds%60).padStart(2,'0');
  });
 }
 const seriesNames=new Map();
 function icon(kind){
  const paths={pc:'M4 4h16v12H4z M8 21h8 M12 16v5',folder:'M3 7V5h6l2 2h10v13H3z',file:'M6 3h8l4 4v14H6z M14 3v5h4',chevron:'M9 5l7 7-7 7'};
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS(svg.namespaceURI,'path');
  svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.classList.add('workspace-icon');path.setAttribute('d',paths[kind]);svg.append(path);return svg;
 }
 function seriesKey(name){return seriesNames.get(name.toLocaleLowerCase('da'))||'';}
 function skipped(name,rules,family){
  name=name.toLocaleLowerCase('da');family=family||seriesKey(name);
  const matches=rules.filter(r=>r.kind==='series'?r.path===family:r.kind==='file'?name===r.path.toLocaleLowerCase('da'):!r.path||name.startsWith(r.path.toLocaleLowerCase('da')+'/'));
  return matches.at(-1)?.skip||false;
 }
 async function fetchBitrates(device){
  const key=scope(device),cached=bitrateCache.get(key);
  if(!device.media_folder||!device.files?.length||bitrateBusy.has(key)||location.hash!=='#conversion'||document.hidden)return;
  const signature=JSON.stringify(device.files.map(f=>[f.name,f.size,!!f.converted]));
  if(cached?.signature===signature&&!cached.pending&&Date.now()-cached.at<60000)return;
  bitrateBusy.add(key);
  let again=false;
  try{
   const data=await api('/api/conversion/devices/'+device.id+'/bitrates');
   if(data.media_folder!==device.media_folder)return;
   bitrateCache.set(key,{signature,at:Date.now(),pending:!!data.pending,files:new Map((data.files||[]).map(f=>[f.name+'\0'+f.size,f]))});
   again=!!data.pending;
  }catch(e){bitrateCache.set(key,{signature,at:Date.now(),pending:false,files:new Map(),error:true});}
  finally{
   bitrateBusy.delete(key);
   if(last)devices(last);
   if(again)setTimeout(()=>{const d=last?.devices.find(d=>scope(d)===key);if(d)fetchBitrates(d);},500);
  }
 }
 function workspace(device,container){
  if(!device.media_folder){container.append(node('p','muted small','Afventer valgt lokaltion i programmet'));return;}
  if(!device.files_updated_at){container.append(node('p','muted small','Afventer filoversigt fra programmet.'));return;}
  if(device.conversion_version!==1)container.append(node('p','muted small','Opdatér Windows-programmet for at starte konvertering direkte fra netværksmappen.'));
  const selected=device.selection;
  const active=selected?.action==='convert'&&!['completed','error','cancelled'].includes(selected.state);
  if(selected){
   const machine=selected.executor==='server'?'server':'pc';
   const states={queued:'Afventer '+machine,selected:'Valgt på pc',converting:'Konverterer på '+machine,encoding:'Konverterer på '+machine,encoded:'Afventer resultatkontrol',ready:'Resultatet er kontrolleret',moving:'Originaltorrenten flyttes til Seeder',completed:'Færdig · film i Bibliotek og originaltorrent i Seeder',error:'Jobbet kunne ikke fuldføres',cancelled:'Konvertering afbrudt'};
   const job=node('div','workspace-job'+(active?' is-active':'')),copy=node('div','workspace-job-copy');
   const phases={probing:'Undersøger originalfilen',metadata:'Bevarer HDR og sporoplysninger',verifying:'Kontrollerer den færdige fil',server_verifying:'Serveren kontrollerer resultatet',source_verifying:'Kontrollerer originalen efter flytningen',publishing:'Lægger filmen i biblioteket'};
   copy.append(node('span','workspace-job-state',selected.state==='error'?states.error:(phases[selected.stage]||states[selected.state]||'Konvertering')));
   const filename=node('strong','workspace-job-name',selected.name.split('/').at(-1));filename.title=selected.name;
   copy.append(filename,node('p','small muted',selected.detail||'FjordSeed kontrollerer resultatet, før filmen lægges i biblioteket.'));
   job.append(copy);
   if(active||selected.state==='completed'){
    const encoding=['encoding','converting'].includes(selected.state)&&(!selected.stage||selected.stage==='encoding');
    const measured=selected.state==='completed'?100:(selected.phase_progress??(encoding?selected.progress:null));
    const progress=node('progress','workspace-job-progress');progress.max=100;
    if(measured!=null){const percent=Math.max(0,Math.min(100,Number(measured)||0));job.append(node('strong','workspace-job-percent',Math.round(percent)+' %'));progress.value=percent;}
    else {job.append(node('strong','workspace-job-percent','Arbejder …'));progress.classList.add('is-indeterminate');}
    progress.setAttribute('aria-label','Fremdrift i det aktuelle trin');job.append(progress);
    if(active&&selected.stage_started_at){const elapsed=node('p','workspace-phase-time muted small');elapsed.dataset.phaseStart=String(selected.stage_started_at);job.append(elapsed);}
   }
   container.append(job);
  }
  const rules=device.skip_rules||[],key=scope(device),cached=bitrateCache.get(key);
  const meta=file=>cached?.files.get(file.name+'\0'+file.size);
  const finished=selected?.state==='completed'&&selected.media_folder===device.media_folder?selected.name.replace(/\.[^/.]+$/,'.mkv'):null;
  const all=(device.files||[]).map(f=>({...f,converted:!!f.converted||f.name===finished,skipped:skipped(f.name,rules)}));
  const queued=(device.queue||[]).filter(q=>q.state==='queued');
  if(queued.length){
   const queue=node('div','workspace-queue'),heading=node('div','workspace-queue-heading');
   heading.append(node('strong','','Konverteringskø · '+queued.length),node('span','small muted','Pc foretrækkes · serveren er fallback'));
   queue.append(heading);
   if(!device.online)queue.append(node('p','muted small',device.server_fallback_ready?'Pc’en er offline. Serverens GPU tager næste ventende job.':'Venter på pc’en eller en klar server-GPU. Køen er gemt.'));
   for(const [index,task] of queued.entries()){
    const row=node('div','workspace-queue-row'),copy=node('div');
    const name=node('strong','',task.name.split('/').at(-1));name.title=task.name;
    copy.append(name,node('p','muted small',task.bitrate+' Mbps'+(task.detail?' · '+task.detail:'')));
    const remove=node('button','quiet','Fjern fra kø');remove.type='button';remove.setAttribute('aria-label','Fjern '+task.name+' fra kø');
    remove.onclick=async()=>{remove.disabled=true;try{await api('/api/conversion/devices/'+device.id+'/queue/'+task.id+'/cancel',{method:'POST'});await load(false);}catch(e){error('#conversion-settings-error',e);remove.disabled=false;}};
    row.append(node('span','workspace-queue-position',String(index+1)),copy,remove);queue.append(row);
   }
   container.append(queue);
  }
  const search=node('input','workspace-search');search.type='search';search.placeholder='Søg i film og serier';
  search.setAttribute('aria-label','Søg i filer på '+device.name);search.value=searches.get(device.id)||'';
  const tools=node('div','workspace-tools'),toggle=node('label','workspace-toggle'),checkbox=node('input');
  checkbox.type='checkbox';checkbox.checked=views.get(key)||false;
  toggle.append(checkbox,document.createTextNode('Vis sprunget over'));
  const summary=node('div','workspace-summary'),files=node('div','workspace-files');
  files.dataset.workspaceScope=key;
  function skipButton(path,kind){
   const sample=kind==='series'?all.find(f=>f.series_key===path)?.name:path;
   const descendants=kind==='folder'?all.filter(f=>!path||f.name.startsWith(path+'/')):[];
   const families=[...new Set(descendants.map(f=>f.series_key))];
   const family=kind==='series'?path:families.length===1?families[0]:null;
   const value=skipped(kind==='folder'?(path?path+'/':'')+'__file__':sample||path,rules,family);
   const text=kind==='series'?(value?'Medtag serien igen':'Spring serien over'):kind==='folder'?(value?'Medtag mappen igen':'Spring mappen over'):(value?'Medtag igen':'Spring over');
   const button=node('button','secondary workspace-skip',text);button.type='button';
   button.dataset.skipPath=path;button.dataset.skipKind=kind;
   button.setAttribute('aria-label',text+' · '+(path||'hele den valgte mappe'));
   button.disabled=!!(active&&selected.media_folder===device.media_folder&&(kind==='series'?seriesKey(selected.name)===path:kind==='file'?selected.name===path:!path||selected.name.startsWith(path+'/')));
   button.onclick=async event=>{
    event.preventDefault();event.stopPropagation();button.disabled=true;
    try{
     const data=await api('/api/conversion/devices/'+device.id+'/skip',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({media_folder:device.media_folder,path,kind,skip:!value})});
     const current=last?.devices.find(d=>d.id===device.id&&d.media_folder===data.media_folder);
     if(current)current.skip_rules=data.skip_rules;
     if(last)devices(last);
    }catch(e){error('#conversion-settings-error',e);button.disabled=false;}
   };
   return button;
  }
  tools.append(toggle);
  function dolbyLabel(info){
   if(info?.dolby_vision===true)return 'Dolby Vision'+(info.dolby_vision_profile?' '+info.dolby_vision_profile:'')+(info.dolby_vision_supported===false?' · profilen understøttes ikke':'');
   if(info?.dolby_vision===false)return 'Ingen Dolby Vision';
   return 'Dolby Vision: '+(cached?.error||(info&&info.state!=='pending')?'ukendt':'henter…');
  }
  function range(rows){
   if(rows.length>1)return rows.length+' filer · fold ud for bitrate og Dolby Vision';
   const info=meta(rows[0]);
   return 'Videobitrate: '+(info?.video_bps?fmt(info.video_bps):!cached?.error&&(!info||info.state==='pending')?'henter…':'ukendt')+' · '+dolbyLabel(info)+' · 1 fil';
  }
  function render(){
   const query=search.value.trim().toLocaleLowerCase('da');searches.set(device.id,search.value);
   const converted=all.filter(f=>f.converted).length,ignored=all.filter(f=>!f.converted&&f.skipped).length;
   const pending=all.length-converted-ignored;
   const matches=all.filter(f=>!f.converted&&(checkbox.checked||!f.skipped)&&f.name.toLocaleLowerCase('da').includes(query));
   const counts=node('div','workspace-counts');
   for(const [value,label] of [[pending,'Mangler konvertering'],[converted,'Konverteret'],[ignored,'Sprunget over']]){const stat=node('div','workspace-count');stat.append(node('strong','',String(value)),node('span','',label));counts.append(stat);}
   summary.replaceChildren(counts,node('p','workspace-update muted small',(query?matches.length+' matcher · ':'')+(matches.length>200?'Viser de første 200 · brug søgningen. ':'')+(device.files_truncated?'Oversigten er begrænset. ':'')+'Sidst opdateret '+new Date(device.files_updated_at*1000).toLocaleString('da-DK')));
   files.replaceChildren();
   const tree={folders:new Map(),files:[],all:[]};
   for(const file of matches){
    const parts=file.name.split('/');let branch=tree;branch.all.push(file);
    for(const part of parts.slice(0,-1)){
     if(!branch.folders.has(part))branch.folders.set(part,{folders:new Map(),files:[],all:[]});
     branch=branch.folders.get(part);branch.all.push(file);
    }
    branch.files.push({...file,label:parts.at(-1)});
   }
   let budget=200;
   function append(branch,parent,path=''){
    for(const [name,child] of [...branch.folders].sort((a,b)=>a[0].localeCompare(b[0],'da'))){
     if(budget<=0)break;
     const full=path+name,folderKey=device.id+'/'+full,details=node('details','workspace-folder');
     details.open=folderOpen.has(folderKey)||!!query;
     const heading=node('summary','workspace-folder-heading'),title=node('span','workspace-folder-name');
     const label=node('strong','',name);label.title=name;title.append(label);
     title.append(node('small','muted',range(child.all)));
     const chevron=icon('chevron');chevron.classList.add('workspace-chevron');heading.append(chevron,icon('folder'),title);
     const folderActions=node('span','workspace-folder-actions');folderActions.append(skipButton(full,'folder'));heading.append(folderActions);
     const series=[...new Set(child.all.map(f=>f.series_key).filter(Boolean))];
     if(series.length===1&&child.all.every(f=>f.series_key))folderActions.append(skipButton(series[0],'series'));
     details.append(heading);
     details.addEventListener('toggle',()=>{if(!details.isConnected)return;if(details.open)folderOpen.add(folderKey);else folderOpen.delete(folderKey);});
     append(child,details,full+'/');parent.append(details);
    }
    for(const file of branch.files){
     if(budget--<=0)break;
     const row=node('div','workspace-file'),label=node('div','workspace-file-name'),info=meta(file);
     const rates=info?.video_bps?' · Videobitrate: '+fmt(info.video_bps):' · Videobitrate: '+(info?.state==='unavailable'||cached?.error?'ukendt':'henter…');
     const filename=node('span','workspace-filename',file.label);filename.title=file.name;
     const metrics=node('div','workspace-metrics');metrics.append(node('span','',new Intl.NumberFormat('da-DK',{maximumFractionDigits:2}).format(file.size/1024**3)+' GiB'),node('span','workspace-video-rate',rates.replace(/^ · /,'')));
     if(info?.total_bps)metrics.append(node('span','','Samlet bitrate: '+fmt(info.total_bps)));
     metrics.append(node('span','workspace-dolby-vision',dolbyLabel(info)));
     label.append(filename,metrics);
     if(file.skipped)label.append(node('span','workspace-skipped','Sprunget over'));
     const current=selected?.name===file.name&&selected?.media_folder===device.media_folder;
     const queuedIndex=queued.findIndex(q=>q.name===file.name&&q.media_folder===device.media_folder);
     const send=node('button','primary workspace-send',queuedIndex>=0?'I kø · '+(queuedIndex+1):current&&active?(selected.state==='queued'?'Afventer GPU…':'Konvertering i gang'):current&&selected.state==='error'?'Prøv igen':'Sæt i kø');send.type='button';send.disabled=device.conversion_version!==1||(current&&!!active)||queuedIndex>=0||file.skipped;
     send.onclick=async()=>{
      send.disabled=true;$('#conversion-settings-error').hidden=true;
      try{
       await api('/api/conversion/devices/'+device.id+'/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({media_folder:device.media_folder,name:file.name,bitrate:Number($('#conversion-bitrate').value)})});
       toast('Konverteringen er sat i kø. Pc’en foretrækkes, ellers bruges serverens GPU.');await load(false);
      }catch(e){error('#conversion-settings-error',e);send.disabled=false;}
     };
     const actions=node('div','workspace-file-actions');actions.append(send,skipButton(file.name,'file'));
     if(file.series_key)actions.append(skipButton(file.series_key,'series'));
     row.append(icon('file'),label,actions);parent.append(row);
    }
   }
   append(tree,files);
   if(!matches.length)files.append(node('p','muted small',query?'Ingen filer matcher søgningen.':pending===0?'Intet mangler i den valgte mappe.':'Ingen filer i denne visning.'));
  }
  checkbox.onchange=()=>{views.set(key,checkbox.checked);render();};search.oninput=render;
  const toolbar=node('div','workspace-toolbar');toolbar.append(search,tools);
  container.append(summary,toolbar,files);render();
 }
 function devices(data){
  last=data;seriesNames.clear();
  for(const d of data.devices)for(const f of d.files||[])if(f.series_key)seriesNames.set(f.name.toLocaleLowerCase('da'),f.series_key);
  const signature=JSON.stringify([data.devices,[...bitrateCache].map(([key,c])=>[key,c.error,[...c.files]])]);
  if(signature===renderedSignature){workerStatus();updatePhaseTimes();return;}
  renderedSignature=signature;
  const scrolls=new Map([...document.querySelectorAll('.workspace-files')].map(el=>[el.dataset.workspaceScope,{top:el.scrollTop,left:el.scrollLeft}]));
  const pageScroll={top:window.scrollY,left:window.scrollX};
  const active=document.activeElement,focusId=active?.dataset.workspaceDevice,selection=active?.selectionStart;
  const list=$('#conversion-devices');list.replaceChildren();
  if(!data.devices.length)list.append(node('p','muted small','Ingen pc’er forbundet endnu.'));
  for(const device of data.devices){
   const row=node('article','workspace-device'),header=node('div','workspace-device-header'),identity=node('div','workspace-identity'),name=node('div','workspace-device-name');
   name.append(node('h3','',device.name),node('span','workspace-connection'+(device.online?' is-online':''),device.online?(device.gpu_ready?'GPU klar':'Forbundet'):'Offline'));
   const description=node('div');description.append(name,node('p','workspace-source muted small',device.media_folder||'Vælg en mappe i pc-programmet'));
   identity.append(icon('pc'),description);header.append(identity);
   const info=node('div','workspace-body');
   workspace(device,info);
   const search=info.querySelector('.workspace-search');if(search)search.dataset.workspaceDevice=device.id;
   const revoke=node('button','quiet workspace-revoke','Fjern adgang');revoke.type='button';
   revoke.onclick=async()=>{revoke.disabled=true;try{await api('/api/conversion/devices/'+device.id+'/revoke',{method:'POST'});await load(false);toast('Pc-tokenet er tilbagekaldt.');}catch(e){error('#conversion-settings-error',e);}finally{revoke.disabled=false;}};
   header.append(revoke);row.append(header,info);list.append(row);
  }
  for(const files of list.querySelectorAll('.workspace-files')){const saved=scrolls.get(files.dataset.workspaceScope);if(saved){files.scrollTop=saved.top;files.scrollLeft=saved.left;}}
  if(focusId){const search=[...list.querySelectorAll('.workspace-search')].find(s=>s.dataset.workspaceDevice===focusId);if(search){search.focus({preventScroll:true});if(selection!=null)search.setSelectionRange(selection,selection);}}
  window.scrollTo(pageScroll.left,pageScroll.top);
  workerStatus();
 }
 function workerStatus(){
  if(!last)return;
  const pc=$('#conversion-target').value==='pc',online=last.devices.filter(d=>d.online&&d.gpu_ready).length;
  $('#conversion-worker-status').textContent=pc?(online?online+' pc-forbindelse(r) er klar. Originalen sendes til pc’en, når downloadet er færdigt.':'Ingen pc er klar endnu. Åbn pc-programmet og forbind det med et token nedenfor.'):(last.conversion_error||(last.conversion_configured?'Serverens GPU-service er installeret.':'Serverens GPU-service er ikke installeret. Vælg en pc, eller tilføj GPU-servicen gennem FjordHub.'));
 }
 async function load(form=true){
  if(location.hash!=='#conversion')return;
  try{
   const data=await api('/api/conversion');
   if(form){$('#conversion-enabled').checked=!!data.conversion_enabled;const rate=String(data.conversion_bitrate||30);const rates=$('#conversion-bitrate');rates.querySelectorAll('[data-legacy]').forEach(option=>option.remove());if(![...rates.options].some(option=>option.value===rate)){const option=new Option(rate+' Mbps – tidligere valg',rate);option.dataset.legacy='true';rates.add(option);}rates.value=rate;$('#conversion-target').value=data.conversion_target||'server';$('#conversion-dolby-vision').value=data.conversion_dolby_vision||'separate';}
   devices(data);
   for(const device of data.devices)fetchBitrates(device);
  }catch(e){error('#conversion-settings-error',e);}
 }
 $('#conversion-target').onchange=workerStatus;
 $('#conversion-settings-form').onsubmit=async e=>{
  e.preventDefault();const button=$('#conversion-settings-save');button.disabled=true;$('#conversion-settings-error').hidden=true;
  try{devices(await api('/api/conversion',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conversion_enabled:$('#conversion-enabled').checked,conversion_bitrate:Number($('#conversion-bitrate').value),conversion_target:$('#conversion-target').value,conversion_dolby_vision:$('#conversion-dolby-vision').value})}));window.dispatchEvent(new Event('conversion-settings-changed'));toast('Konverteringsvalget er gemt.');}
  catch(e){error('#conversion-settings-error',e);}finally{button.disabled=false;}
 };
 $('#conversion-device-form').onsubmit=async e=>{
  e.preventDefault();const button=$('#conversion-device-create');button.disabled=true;$('#conversion-settings-error').hidden=true;
  try{const data=await api('/api/conversion/devices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('#conversion-device-name').value})});$('#conversion-token-secret').value='fsp1_'+btoa(JSON.stringify({server:location.origin,token:data.token})).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');$('#conversion-token-result').hidden=false;await load(false);$('#conversion-token-secret').focus();$('#conversion-token-secret').select();}
  catch(e){error('#conversion-settings-error',e);}finally{button.disabled=false;}
 };
 window.addEventListener('hashchange',()=>load());setInterval(()=>load(false),5000);setInterval(updatePhaseTimes,1000);load();
})();
