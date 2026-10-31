/* Server-backed drafts remain drafts until the normal manual form is submitted. */
(() => {
 'use strict';
 let snapshot={items:[],count:0},loading=false,opening=false;
 const banner=$('#manual-package-banner'),open=$('#manual-package-open'),clear=$('#manual-package-clear');
 async function refreshPackage(){
  if(loading)return;loading=true;
  try{
   snapshot=await api('/api/manual-package');banner.hidden=!snapshot.count;
   $('#manual-package-count').textContent=`${snapshot.count} ${snapshot.count===1?'torrent ligger klar':'torrents ligger klar'}. Ingen download er startet.`;
  }catch(_){/* A temporary connection failure must not erase an existing draft. */}
  finally{loading=false;}
 }
 async function remove(ids){
  await api('/api/manual-package/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids})});
  await refreshPackage();
 }
 clear.onclick=async()=>{
  clear.disabled=true;$('#manual-package-error').hidden=true;
  try{await remove(snapshot.items.map(item=>item.id));}catch(e){error('#manual-package-error',e);}finally{clear.disabled=false;}
 };
 open.onclick=async()=>{
  if(opening)return;
  if(document.querySelector('dialog[open]')){toast('Luk den åbne dialog, før du åbner pakken.');return;}
  opening=true;open.disabled=true;clear.disabled=true;$('#manual-package-error').hidden=true;open.textContent='Henter pakken…';
  try{
   const data=await api('/api/manual-package');
   if(!data.items.length){await refreshPackage();return;}
   const files=new Array(data.items.length),ids=new Map();let next=0;
   await Promise.all(Array.from({length:Math.min(3,data.items.length)},async()=>{
    while(next<data.items.length){
     const index=next++,item=data.items[index];
     const response=await fetch(`/api/manual-package/${encodeURIComponent(item.id)}/file`,{signal:AbortSignal.timeout(20000)});
     if(!response.ok)throw Error('Pakken er ændret, eller forbindelsen er afbrudt. Åbn pakken igen.');
     const file=new File([await response.blob()],item.name,{type:'application/x-bittorrent'});files[index]=file;ids.set(file,item.id);
    }
   }));
   if(document.querySelector('dialog[open]'))throw Error('Luk den åbne dialog, og åbn pakken igen.');
   window.TorrentBatch.reset();pendingTorrent=null;$('#ratio-form').reset();
   $('#ratio-error').hidden=true;$('#ratio-dialog').showModal();
   window.TorrentBatch.open(files,{ids,remove:file=>remove([ids.get(file)])});
   updateSeedingFields('ratio');$('#ratio-action').focus();
  }catch(e){error('#manual-package-error',e);}finally{opening=false;open.disabled=false;clear.disabled=false;open.textContent='Åbn pakken';}
 };
 document.addEventListener('fjordseed:package-updated',refreshPackage);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshPackage();});
 setInterval(()=>{if(!document.hidden)refreshPackage();},10000);refreshPackage();
})();
