(() => {
 let last,renderedSignature;
 const folderOpen=new Set(),searches=new Map();
 const views=new Map(),bitrateCache=new Map(),bitrateBusy=new Set();
 const scope=d=>d.id+'\0'+d.media_folder;
 const fmt=n=>new Intl.NumberFormat('da-DK',{maximumFractionDigits:0}).format(n/1000)+' kb/s';
 const seriesNames=new Map();
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
  container.append(node('p','muted small','Mappe på pc: '+device.media_folder));
  if(!device.files_updated_at){container.append(node('p','muted small','Afventer filoversigt fra programmet.'));return;}
  container.append(node('p','muted small','Send til pc starter GPU-konverteringen direkte fra netværksmappen med den valgte videobitrate.'));
  if(device.conversion_version!==1)container.append(node('p','muted small','Opdatér Windows-programmet for at starte konvertering direkte fra netværksmappen.'));
  const selected=device.selection;
  const active=selected?.action==='convert'&&!['completed','error','cancelled'].includes(selected.state);
  if(selected){
   const states={queued:'Afventer pc',selected:'Valgt på pc',converting:'Konverterer på pc',encoding:'Konverterer på pc',encoded:'Afventer resultatkontrol',ready:'Resultatet er kontrolleret',moving:'Originaltorrenten flyttes til Seeder',completed:'Færdig · film i Bibliotek og originaltorrent i Seeder',error:'Jobbet kunne ikke fuldføres',cancelled:'Konvertering afbrudt'};
   container.append(node('p','muted small',(states[selected.state]||'Konvertering')+' · '+selected.name+(selected.progress>0?' · '+Math.round(selected.progress)+' %':'')+(selected.detail?' · '+selected.detail:'')));
  }
  const rules=device.skip_rules||[],key=scope(device),cached=bitrateCache.get(key);
  const meta=file=>cached?.files.get(file.name+'\0'+file.size);
  const finished=selected?.state==='completed'&&selected.media_folder===device.media_folder?selected.name.replace(/\.[^/.]+$/,'.mkv'):null;
  const all=(device.files||[]).map(f=>({...f,converted:!!f.converted||f.name===finished,skipped:skipped(f.name,rules)}));
  const search=node('input','workspace-search');search.type='search';search.placeholder='Søg i film og serier';
  search.setAttribute('aria-label','Søg i filer på '+device.name);search.value=searches.get(device.id)||'';
  const tools=node('div','workspace-tools'),toggle=node('label','workspace-toggle'),checkbox=node('input');
  checkbox.type='checkbox';checkbox.checked=views.get(key)||false;
  toggle.append(checkbox,document.createTextNode('Vis sprunget over'));
  const summary=node('p','muted small workspace-summary'),files=node('div','workspace-files');
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
  tools.append(toggle,skipButton('','folder'));
  function range(rows){
   if(rows.length>1)return rows.length+' filer · fold ud for bitrate pr. fil';
   const info=meta(rows[0]);
   return 'Videobitrate: '+(info?.video_bps?fmt(info.video_bps):!cached?.error&&(!info||info.state==='pending')?'henter…':'ukendt')+' · 1 fil';
  }
  function render(){
   const query=search.value.trim().toLocaleLowerCase('da');searches.set(device.id,search.value);
   const converted=all.filter(f=>f.converted).length,ignored=all.filter(f=>!f.converted&&f.skipped).length;
   const pending=all.length-converted-ignored;
   const matches=all.filter(f=>!f.converted&&(checkbox.checked||!f.skipped)&&f.name.toLocaleLowerCase('da').includes(query));
   summary.textContent=pending+' mangler · '+converted+' konverterede skjult · '+ignored+' sprunget over'+(query?' · '+matches.length+' matcher':'')+(matches.length>200?' · viser de første 200, brug søgningen':'')+(device.files_truncated?' · oversigten er begrænset':'')+' · opdateret '+new Date(device.files_updated_at*1000).toLocaleString('da-DK');
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
     const heading=node('summary','workspace-folder-heading'),title=node('span','workspace-folder-name',name);
     title.append(node('small','muted',range(child.all)));
     heading.append(title,skipButton(full,'folder'));
     const series=[...new Set(child.all.map(f=>f.series_key).filter(Boolean))];
     if(series.length===1&&child.all.every(f=>f.series_key))heading.append(skipButton(series[0],'series'));
     details.append(heading);
     details.addEventListener('toggle',()=>{if(!details.isConnected)return;if(details.open)folderOpen.add(folderKey);else folderOpen.delete(folderKey);});
     append(child,details,full+'/');parent.append(details);
    }
    for(const file of branch.files){
     if(budget--<=0)break;
     const row=node('div','workspace-file'),label=node('div','workspace-file-name'),info=meta(file);
     const rates=info?.video_bps?' · Videobitrate: '+fmt(info.video_bps):' · Videobitrate: '+(info?.state==='unavailable'||cached?.error?'ukendt':'henter…');
     label.append(node('span','',file.label),node('p','muted small',new Intl.NumberFormat('da-DK',{maximumFractionDigits:2}).format(file.size/1024**3)+' GiB'+rates+(info?.total_bps?' · Samlet bitrate: '+fmt(info.total_bps):'')));
     if(file.skipped)label.append(node('span','workspace-skipped','Sprunget over'));
     const current=selected?.name===file.name&&selected?.media_folder===device.media_folder;
     const send=node('button','secondary',current&&active?(selected.state==='queued'?'Afventer pc…':'Konvertering i gang'):current&&selected.state==='error'?'Prøv igen':'Send til pc');send.type='button';send.disabled=device.conversion_version!==1||!!active||file.skipped;
     send.onclick=async()=>{
      send.disabled=true;$('#conversion-settings-error').hidden=true;
      try{
       await api('/api/conversion/devices/'+device.id+'/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({media_folder:device.media_folder,name:file.name,bitrate:Number($('#conversion-bitrate').value)})});
       toast('Konverteringen er sendt til pc’en.');await load(false);
      }catch(e){error('#conversion-settings-error',e);send.disabled=false;}
     };
     const actions=node('div','workspace-file-actions');actions.append(send,skipButton(file.name,'file'));
     if(file.series_key)actions.append(skipButton(file.series_key,'series'));
     row.append(label,actions);parent.append(row);
    }
   }
   append(tree,files);
   if(!matches.length)files.append(node('p','muted small',query?'Ingen filer matcher søgningen.':pending===0?'Intet mangler i den valgte mappe.':'Ingen filer i denne visning.'));
  }
  checkbox.onchange=()=>{views.set(key,checkbox.checked);render();};search.oninput=render;
  container.append(search,tools,summary,files);render();
 }
 function devices(data){
  last=data;seriesNames.clear();
  for(const d of data.devices)for(const f of d.files||[])if(f.series_key)seriesNames.set(f.name.toLocaleLowerCase('da'),f.series_key);
  const signature=JSON.stringify([data.devices,[...bitrateCache].map(([key,c])=>[key,c.error,[...c.files]])]);
  if(signature===renderedSignature){workerStatus();return;}
  renderedSignature=signature;
  const scrolls=new Map([...document.querySelectorAll('.workspace-files')].map(el=>[el.dataset.workspaceScope,{top:el.scrollTop,left:el.scrollLeft}]));
  const pageScroll={top:window.scrollY,left:window.scrollX};
  const active=document.activeElement,focusId=active?.dataset.workspaceDevice,selection=active?.selectionStart;
  const list=$('#conversion-devices');list.replaceChildren();
  if(!data.devices.length)list.append(node('p','muted small','Ingen pc’er forbundet endnu.'));
  for(const device of data.devices){
   const row=node('div','storage-summary workspace-device');
   const info=node('div');info.append(node('strong','',device.name),node('p','muted small',device.online?(device.gpu_ready?'Forbundet · GPU klar':'Forbundet'):device.last_seen?'Offline · sidst set '+new Date(device.last_seen*1000).toLocaleString('da-DK'):'Afventer første forbindelse'));
   workspace(device,info);
   const search=info.querySelector('.workspace-search');if(search)search.dataset.workspaceDevice=device.id;
   const revoke=node('button','secondary','Fjern adgang');revoke.type='button';
   revoke.onclick=async()=>{revoke.disabled=true;try{await api('/api/conversion/devices/'+device.id+'/revoke',{method:'POST'});await load(false);toast('Pc-tokenet er tilbagekaldt.');}catch(e){error('#conversion-settings-error',e);}finally{revoke.disabled=false;}};
   row.append(info,revoke);list.append(row);
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
   if(form){$('#conversion-enabled').checked=!!data.conversion_enabled;const rate=String(data.conversion_bitrate||30);const rates=$('#conversion-bitrate');rates.querySelectorAll('[data-legacy]').forEach(option=>option.remove());if(![...rates.options].some(option=>option.value===rate)){const option=new Option(rate+' Mbps – tidligere valg',rate);option.dataset.legacy='true';rates.add(option);}rates.value=rate;$('#conversion-target').value=data.conversion_target||'server';}
   devices(data);
   for(const device of data.devices)fetchBitrates(device);
  }catch(e){error('#conversion-settings-error',e);}
 }
 $('#conversion-target').onchange=workerStatus;
 $('#conversion-settings-form').onsubmit=async e=>{
  e.preventDefault();const button=$('#conversion-settings-save');button.disabled=true;$('#conversion-settings-error').hidden=true;
  try{devices(await api('/api/conversion',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conversion_enabled:$('#conversion-enabled').checked,conversion_bitrate:Number($('#conversion-bitrate').value),conversion_target:$('#conversion-target').value})}));window.dispatchEvent(new Event('conversion-settings-changed'));toast('Konverteringsvalget er gemt.');}
  catch(e){error('#conversion-settings-error',e);}finally{button.disabled=false;}
 };
 $('#conversion-device-form').onsubmit=async e=>{
  e.preventDefault();const button=$('#conversion-device-create');button.disabled=true;$('#conversion-settings-error').hidden=true;
  try{const data=await api('/api/conversion/devices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('#conversion-device-name').value})});$('#conversion-token-secret').value='fsp1_'+btoa(JSON.stringify({server:location.origin,token:data.token})).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');$('#conversion-token-result').hidden=false;await load(false);$('#conversion-token-secret').focus();$('#conversion-token-secret').select();}
  catch(e){error('#conversion-settings-error',e);}finally{button.disabled=false;}
 };
 window.addEventListener('hashchange',()=>load());setInterval(()=>load(false),5000);load();
})();
