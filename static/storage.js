(() => {
 let selectedPath='', requestId=0;
 const dialog=$('#storage-dialog');
 async function load(){
  if(location.hash!=='#storage')return;
  $('#storage-error').hidden=true;
  try{const data=await api('/api/storage');$('#storage-current').textContent=data.path;$('#storage-buffer').textContent=data.buffer;}
  catch(e){error('#storage-error',e);}
 }
 async function browse(path=''){
  const id=++requestId;selectedPath='';$('#storage-select').disabled=true;
  $('#storage-browser-error').hidden=true;$('#storage-directories').replaceChildren(node('p','muted','Henter mapper…'));
  if(!dialog.open)dialog.showModal();
  try{
   const data=await api('/api/storage?browse=1&path='+encodeURIComponent(path));if(id!==requestId)return;
   selectedPath=data.path;$('#storage-browser-path').textContent=data.path||'Tilgængelige mapper på serveren';
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
  const button=$('#storage-select');button.disabled=true;$('#storage-browser-error').hidden=true;
  try{await api('/api/storage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:selectedPath})});dialog.close();toast('Mappe gemt. Nye downloads starter i bufferen.');await load();}
  catch(e){error('#storage-browser-error',e);}
  finally{button.disabled=false;}
 };
 $('#storage-proxmox').onclick=async()=>{
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
    item.append(actions);list.append(item);
   }
   for(const message of data.errors||[])list.append(node('p','error',message));
   if(!(data.storages||[]).length)list.append(node('p','muted','Ingen Proxmox-lagre tilgængelige. Brug “Vælg mappe” til serverens mapper.'));
  }catch(e){list.replaceChildren();error('#storage-error',e);}
  finally{button.disabled=false;}
 };
 window.addEventListener('hashchange',load);load();
})();
