(() => {
 const list=$('#library-conversion-list');
 let items=[],busy=false,loaded=false;
 const rates={20:'spar plads',30:'balance',40:'høj kvalitet'};
 const size=n=>new Intl.NumberFormat('da-DK',{maximumFractionDigits:2}).format(n/1024**3)+' GiB';
 function render(){
  const query=$('#library-conversion-search').value.trim().toLocaleLowerCase('da');
  const matches=items.filter(item=>item.name.toLocaleLowerCase('da').includes(query));
  list.replaceChildren();
  $('#library-conversion-summary').textContent=matches.length+' film'+(matches.length>100?' · viser de første 100, brug søgningen':'');
  if(!matches.length)list.append(node('p','muted small','Ingen film fundet i Behold.'));
  for(const item of matches.slice(0,100)){
   const row=node('div','library-film'),info=node('div','library-film-info');
   info.append(node('strong','',item.name),node('p','muted small',size(item.size)));
   if(item.converted){
    const flag=item.converted;
    const when=flag.converted_at?' · '+new Date(flag.converted_at*1000).toLocaleString('da-DK'):'';
    info.append(node('span','library-converted','✓ Konverteret'+(flag.bitrate?' · '+flag.bitrate+' Mbps':'')+when));
   }else if(item.reason)info.append(node('p','muted small',item.reason));
   const button=node('button','secondary','Send til pc');button.type='button';button.disabled=!item.eligible;
   button.onclick=async()=>{
    button.disabled=true;$('#library-conversion-error').hidden=true;
    try{
     await api('/api/conversion/library',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:item.id,bitrate:Number($('#library-conversion-bitrate').value)})});
     toast('Filmen er sat i kø til pc-konvertering.');await load();
    }catch(e){error('#library-conversion-error',e);button.disabled=false;}
   };
   row.append(info,button);list.append(row);
  }
 }
 async function load(){
  if(location.hash!=='#conversion'||busy)return;
  busy=true;
  try{
   const data=await api('/api/conversion/library');
   items=data.items||[];
   const jobs=$('#library-conversion-jobs');jobs.replaceChildren();
   for(const job of data.jobs||[]){
    const row=node('div','library-film'),info=node('div','library-film-info');
    const phase=job.phase==='moving'?'qBittorrent flytter originalen til Seeder':job.detail||'Venter på en tilsluttet pc';
    info.append(node('strong','',job.name),node('p','muted small',job.bitrate+' Mbps · '+(rates[job.bitrate]||'')+' · '+phase));
    row.append(info);
    if(job.state==='error'&&job.phase==='queued'){
     const retry=node('button','secondary','Prøv igen');retry.type='button';
     retry.onclick=async()=>{retry.disabled=true;try{await api('/api/conversion/library/'+job.id+'/retry',{method:'POST'});await load();}catch(e){error('#library-conversion-error',e);retry.disabled=false;}};
     row.append(retry);
    }
    if(['queued','preparing'].includes(job.phase)){
     const cancel=node('button','secondary','Annullér');cancel.type='button';
     cancel.onclick=async()=>{cancel.disabled=true;try{await api('/api/conversion/library/'+job.id+'/cancel',{method:'POST'});await load();toast('Konverteringen er annulleret. Originalen er bevaret.');}catch(e){error('#library-conversion-error',e);cancel.disabled=false;}};
     row.append(cancel);
    }
    jobs.append(row);
   }
   $('#library-conversion-error').hidden=true;render();loaded=true;
   if(data.truncated)$('#library-conversion-summary').textContent+=' · listen er begrænset til 5.000 filer';
  }catch(e){error('#library-conversion-error',e);if(!loaded)$('#library-conversion-summary').textContent='Listen kræver en kørende qBittorrent med VPN.';}
  finally{busy=false;}
 }
 $('#library-conversion-search').addEventListener('input',render);
 $('#library-conversion-refresh').onclick=load;
 window.addEventListener('hashchange',load);
 setInterval(()=>{if(!document.hidden)load();},15000);
 load();
})();
