(() => {
 let selectedPath='', requestId=0, locked=true;
 const dialog=$('#storage-dialog');
 async function load(){
  if(location.hash!=='#storage')return;
  $('#storage-error').hidden=true;
  locked=true;
  $('#storage-browse').disabled=true;$('#storage-proxmox').disabled=true;
  $('#storage-pools').hidden=true;
  try{
   const data=await api('/api/storage');locked=false;
   $('#storage-current').textContent=data.path;$('#storage-buffer').textContent=data.buffer||'Slået fra · direkte download';
   $('#storage-browse').disabled=locked;$('#storage-proxmox').disabled=locked;
   $('#storage-selection-note').hidden=locked;
   document.querySelectorAll('[data-storage-mode-note]').forEach(n=>n.textContent=data.streaming_enabled?'Nye downloads starter på bufferdisken. Færdige filer, der skal beholdes, flyttes til den valgte mappe. Buffer og destination kan ligge på hver sin disk.':'Buffer er slået fra. Nye downloads skriver direkte til deres endelige mappe.');
  }
  catch(e){error('#storage-error',e);}
 }
 async function browse(path=''){
  if(locked)return;
  const id=++requestId;selectedPath='';$('#storage-select').disabled=true;
  $('#storage-browser-error').hidden=true;$('#storage-directories').replaceChildren(node('p','muted','Henter mapper…'));
  if(!dialog.open)dialog.showModal();
  try{
   const data=await api('/api/storage?browse=1&path='+encodeURIComponent(path));if(id!==requestId)return;
   selectedPath=data.path;$('#storage-browser-path').textContent=data.path||'Tilgængelige mapper på serveren';
   $('#storage-create-form').hidden=!selectedPath||['/mnt','/media','/srv'].includes(selectedPath);
   $('#storage-free').textContent=data.free_bytes===undefined?'':size(data.free_bytes)+' ledig';
   const list=$('#storage-directories');list.replaceChildren();
   const add=(label,value)=>{const button=node('button','secondary storage-folder',label);button.type='button';button.onclick=()=>browse(value);list.append(button);};
   if(data.parent!==null)add('↑ En mappe op',data.parent);
   for(const entry of data.directories)add('▸ '+entry.name,entry.path);
   if(!data.directories.length)list.append(node('p','muted','Ingen undermapper.'));
   if(data.truncated)list.append(node('p','muted','Kun de første 500 mapper vises.'));
   $('#storage-select').disabled=!selectedPath||['/mnt','/media','/srv'].includes(selectedPath);
  }catch(e){if(id===requestId){$('#storage-directories').replaceChildren();error('#storage-browser-error',e);}}
 }
 $('#storage-browse').onclick=()=>browse();
 $('#storage-select').onclick=async()=>{
  if(locked)return;
  const button=$('#storage-select');button.disabled=true;$('#storage-browser-error').hidden=true;
  try{await api('/api/storage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:selectedPath})});dialog.close();window.dispatchEvent(new Event('storage-changed'));toast('Mappe til beholdte filer er gemt. Bufferdisken er uændret.');await load();}
  catch(e){error('#storage-browser-error',e);}
  finally{button.disabled=false;}
 };
 $('#storage-create-form').onsubmit=async event=>{
  event.preventDefault();const button=event.submitter;button.disabled=true;
  try{const data=await api('/api/storage/folders',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({parent:selectedPath,name:$('#storage-folder-name').value})});$('#storage-folder-name').value='';await browse(data.path);}
  catch(e){error('#storage-browser-error',e);}finally{button.disabled=false;}
 };
 async function showMount(row){
  $('#storage-error').hidden=true;
  try{const data=await api('/api/storage/mount-plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({storage_id:row.id})});$('#storage-mount-message').textContent=data.message;$('#storage-mount-command').textContent=data.commands;$('#storage-mount-copy-status').textContent='';$('#storage-mount-dialog').showModal();}
  catch(e){error('#storage-error',e);}
 }
 $('#storage-mount-copy').onclick=async()=>{try{await navigator.clipboard.writeText($('#storage-mount-command').textContent);$('#storage-mount-copy-status').textContent='Kommandoen er kopieret.';}catch{$('#storage-mount-copy-status').textContent='Markér kommandoen og kopiér den manuelt.';}};
 $('#storage-mount-refresh').onclick=()=>{$('#storage-mount-dialog').close();$('#storage-proxmox').click();};
 $('#storage-proxmox').onclick=async()=>{
  if(locked)return;
  const button=$('#storage-proxmox');button.disabled=true;$('#storage-error').hidden=true;
  $('#storage-pools').hidden=false;const list=$('#storage-pool-list');list.replaceChildren(node('p','muted','Henter Proxmox-lagre…'));
  try{
   const data=await api('/api/storage?proxmox=1');list.replaceChildren();
   for(const row of data.storages||[]){
    const item=node('div','storage-row'),text=node('div');text.append(node('strong','',row.id),node('p','muted small',row.type+' · '+size(row.free_bytes)+' ledig'));item.append(text);
    const actions=node('div','storage-actions');
    for(const path of row.paths||[]){
     const mount=(data.mounts||[]).filter(m=>path===m.path||path.startsWith(m.path+'/')).sort((a,b)=>b.path.length-a.path.length)[0];
     const readonly=mount?.read_only===true;
     const b=node('button','secondary',path+(readonly?' · Kun læsning':''));b.type='button';b.disabled=readonly;b.onclick=()=>browse(path);actions.append(b);
    }
    if(!(row.paths||[]).length)text.append(node('p','muted small',row.reason||'Tilslut lageret i FjordHub først.'));
    if(row.online&&row.path&&['dir','nfs','cifs','btrfs'].includes(row.type)&&(!(row.paths||[]).length||!(row.paths||[]).some(path=>(data.mounts||[]).some(m=>!m.read_only&&(path===m.path||path.startsWith(m.path+'/')))))){
     const b=node('button','secondary','Tilslut storagepool til Fjordseed');b.type='button';b.onclick=()=>showMount(row);actions.append(b);
    }
    item.append(actions);list.append(item);
   }
   for(const message of data.errors||[])list.append(node('p','error',message));
   if(!(data.storages||[]).length)list.append(node('p','muted','Ingen Proxmox-lagre tilgængelige. Brug “Vælg mappe” til serverens mapper.'));
  }catch(e){list.replaceChildren();error('#storage-error',e);}
  finally{button.disabled=false;}
 };
 window.addEventListener('hashchange',load);load();
})();
