(() => {
 let last;
 const folderOpen=new Set(),searches=new Map();
 function workspace(device,container){
  if(!device.media_folder){
   container.append(node('p','muted small','Afventer valgt lokaltion i programmet'));
   return;
  }
  container.append(node('p','muted small','Mappe på pc: '+device.media_folder));
  if(!device.files_updated_at){container.append(node('p','muted small','Afventer filoversigt fra programmet.'));return;}
  container.append(node('p','muted small','Send til pc starter GPU-konverteringen direkte fra netværksmappen med den valgte videobitrate.'));
  if(device.conversion_version!==1)container.append(node('p','muted small','Opdatér Windows-programmet for at starte konvertering direkte fra netværksmappen.'));
  const selected=device.selection;
  if(selected){
   const states={queued:'Afventer pc',selected:'Valgt på pc',converting:'Konverterer på pc',encoding:'Konverterer på pc',encoded:'Afventer resultatkontrol',ready:'Resultatet er kontrolleret',moving:'Originaltorrenten flyttes til Seeder',completed:'Færdig · film i Bibliotek og originaltorrent i Seeder',error:'Jobbet kunne ikke fuldføres',cancelled:'Konvertering afbrudt'};
   container.append(node('p','muted small',(states[selected.state]||'Konvertering')+' · '+selected.name+(selected.progress>0?' · '+Math.round(selected.progress)+' %':'')+(selected.detail?' · '+selected.detail:'')));
  }
  const search=node('input','workspace-search');search.type='search';search.placeholder='Søg i film og serier';
  search.setAttribute('aria-label','Søg i filer på '+device.name);search.value=searches.get(device.id)||'';
  const summary=node('p','muted small'),files=node('div','workspace-files');
  const render=()=>{
   const query=search.value.toLocaleLowerCase('da');searches.set(device.id,search.value);
   const matches=(device.files||[]).filter(f=>f.name.toLocaleLowerCase('da').includes(query));
   summary.textContent=matches.length+' videofiler'+(matches.length>200?' · viser de første 200, brug søgningen':'')+(device.files_truncated?' · oversigten er begrænset':'')+' · opdateret '+new Date(device.files_updated_at*1000).toLocaleString('da-DK');
   files.replaceChildren();
   const tree={folders:new Map(),files:[]};
   for(const file of matches.slice(0,200)){
    const parts=file.name.split('/');let branch=tree;
    for(const part of parts.slice(0,-1)){
     if(!branch.folders.has(part))branch.folders.set(part,{folders:new Map(),files:[]});
     branch=branch.folders.get(part);
    }
    branch.files.push({...file,label:parts.at(-1)});
   }
   function append(branch,parent,path=''){
    for(const [name,child] of [...branch.folders].sort((a,b)=>a[0].localeCompare(b[0],'da'))){
     const key=device.id+'/'+path+name,details=node('details','workspace-folder');
     details.open=folderOpen.has(key)||!!query;
     details.append(node('summary','',name));
     details.addEventListener('toggle',()=>{if(details.open)folderOpen.add(key);else folderOpen.delete(key);});
     append(child,details,path+name+'/');parent.append(details);
    }
    for(const file of branch.files){
     const row=node('div','workspace-file'),label=node('div','workspace-file-name');
     label.append(node('span','',file.label),node('p','muted small',new Intl.NumberFormat('da-DK',{maximumFractionDigits:2}).format(file.size/1024**3)+' GiB'));
     if(file.converted)label.append(node('span','library-converted','✓ Konverteret · '+file.bitrate+' Mbps'));
     const current=selected?.name===file.name&&selected?.media_folder===device.media_folder;
     const active=selected?.action==='convert'&&!['completed','error','cancelled'].includes(selected.state);
     const button=node('button','secondary',file.converted?'Konverteret':current&&active?(selected.state==='queued'?'Afventer pc…':'Konvertering i gang'):current&&selected.state==='error'?'Prøv igen':'Send til pc');button.type='button';button.disabled=device.conversion_version!==1||!!active||!!file.converted;
     button.onclick=async()=>{
      button.disabled=true;$('#conversion-settings-error').hidden=true;
      try{
       await api('/api/conversion/devices/'+device.id+'/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({media_folder:device.media_folder,name:file.name,bitrate:Number($('#conversion-bitrate').value)})});
       toast('Konverteringen er sendt til pc’en.');await load(false);
      }catch(e){error('#conversion-settings-error',e);button.disabled=false;}
     };
     row.append(label,button);parent.append(row);
    }
   }
   append(tree,files);
   if(!matches.length)files.append(node('p','muted small',query?'Ingen filer matcher søgningen.':'Ingen videofiler i den valgte mappe.'));
  };
  search.oninput=render;container.append(search,summary,files);render();
 }
 function devices(data){
  last=data;
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
  if(focusId){const search=[...list.querySelectorAll('.workspace-search')].find(s=>s.dataset.workspaceDevice===focusId);if(search){search.focus();if(selection!=null)search.setSelectionRange(selection,selection);}}
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
  }catch(e){error('#conversion-settings-error',e);}
 }
 $('#conversion-target').onchange=workerStatus;
 window.addEventListener('workspace-find',event=>{
  if(!last)return;
  for(const device of last.devices)searches.set(device.id,event.detail);
  devices(last);
 });
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
