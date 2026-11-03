(() => {
 'use strict';
 let token=null,offset=0,timer=null,generation=0,pollSequence=0,loading=false,loaded=false,installing=false;
 const message=text=>{$('#search-status').textContent=text;};
 const fail=e=>error('#search-error',e);
 const post=(url,data)=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 function running(value){$('#search-stop').hidden=!value;}
 async function engines(){
  const data=await api('/api/search/plugins');
  const select=$('#search-engine'),selected=select.value;
  select.replaceChildren(new Option('Alle søgemaskiner på én gang','enabled'));
  const active=(data.plugins||[]).filter(p=>p.enabled);
  for(const p of active)select.append(new Option(p.fullName||p.name,p.name));
  if([...select.options].some(p=>p.value===selected))select.value=selected;
  $('#search-engine-status').textContent=active.length?active.map(p=>p.fullName||p.name).join(' · '):'Ingen aktive søgemaskiner endnu. Vælg “Tilføj alle søgemaskiner” for at komme i gang.';
  const catalog=$('#search-install-engine');catalog.replaceChildren();
  for(const [name,label] of Object.entries(data.catalog||{}))catalog.append(new Option(label,name));
  if(!active.length){$('#search-engines').hidden=false;$('#search-engines-toggle').setAttribute('aria-expanded','true');}
  loaded=true;
  return data;
 }
 function render(data){
  const target=$('#search-results');target.replaceChildren();
  for(const [index,result] of (data.results||[]).entries()){
   const row=node('article','search-result'),info=node('div','search-result-info'),meta=node('div','search-result-meta');
   info.append(node('h3','',result.fileName||'Unavngivet torrent'));
   for(const text of [result.fileSize>0?size(result.fileSize,true):'Ukendt størrelse',
    (result.nbSeeders>=0?result.nbSeeders:'?')+' seeders',(result.nbLeechers>=0?result.nbLeechers:'?')+' leechers',result.engineName||result.siteUrl||'Ukendt kilde'])meta.append(node('span','',text));
   info.append(meta);const button=node('button','secondary','Hent');button.type='button';
   button.setAttribute('aria-label','Hent '+(result.fileName||'torrent'));
   const job=token,resultOffset=offset+index;
   button.onclick=async()=>{
    button.disabled=true;$('#search-error').hidden=true;
    try{const source=await post('/api/search/'+job,{action:'resolve',offset:resultOffset});openSearchTorrent(source);}
    catch(e){fail(e);}finally{button.disabled=false;}
   };
   row.append(info,button);target.append(row);
  }
  const total=Number(data.total)||0,isRunning=data.status==='Running';
  running(isRunning);
  message(isRunning?'Søger… '+total+' resultater fundet.':total?total+' resultater fundet.':'Ingen resultater. Prøv et andet navn eller en anden søgemaskine.');
  $('#search-prev').hidden=offset===0;$('#search-next').hidden=offset+50>=total;
  $('#search-page').textContent=total?'Side '+(offset/50+1)+' af '+Math.ceil(total/50):'';
  return isRunning;
 }
 async function poll(version=generation){
  clearTimeout(timer);
  if(!token||version!==generation)return;
  const sequence=++pollSequence;
  try{const data=await api('/api/search/'+token+'?offset='+offset);if(version!==generation||sequence!==pollSequence)return;
   if(render(data))timer=setTimeout(()=>poll(version),2000);
  }catch(e){if(version===generation&&sequence===pollSequence){running(false);message('Søgningen kunne ikke opdateres.');fail(e);}}
 }
 $('#search-engines-toggle').onclick=()=>{const panel=$('#search-engines');panel.hidden=!panel.hidden;$('#search-engines-toggle').setAttribute('aria-expanded',String(!panel.hidden));if(!loaded)engines().catch(fail);};
 $('#search-reload').onclick=()=>engines().catch(fail);
 async function install(name){
  if(installing||loading)return;installing=true;$('#search-error').hidden=true;
  for(const id of ['search-install','search-install-all','search-submit','search-reload','search-engine','search-install-engine'])$('#'+id).disabled=true;
  try{
   const result=await post('/api/search/plugins',{name});
   const requested=result.requested||[name];
   if(name==='all')$('#search-engine').value='enabled';
   let missing=requested;
   for(let attempt=0;attempt<20;attempt++){
    const data=await engines(),ready=new Set((data.plugins||[]).filter(p=>p.enabled).map(p=>p.name));
    missing=requested.filter(n=>!ready.has(n));
    message(missing.length?`Tilføjer søgemaskiner… ${requested.length-missing.length} af ${requested.length} klar.`:name==='all'?'Alle søgemaskiner er klar. Din næste søgning søger i dem alle.':'Søgemaskinen er klar.');
    if(!missing.length)break;
    await new Promise(resolve=>setTimeout(resolve,1000));
   }
   if(missing.length)throw Error('Disse søgemaskiner er endnu ikke klar: '+missing.join(', ')+'. Opdatér listen, eller prøv at tilføje dem igen.');
  }catch(e){fail(e);}finally{
   installing=false;for(const id of ['search-install','search-install-all','search-submit','search-reload','search-engine','search-install-engine'])$('#'+id).disabled=false;
  }
 }
 $('#search-install').onclick=()=>install($('#search-install-engine').value);
 $('#search-install-all').onclick=()=>install('all');
 $('#search-form').onsubmit=async event=>{
  event.preventDefault();if(loading||installing)return;loading=true;$('#search-submit').disabled=true;$('#search-error').hidden=true;
  const version=++generation;clearTimeout(timer);token=null;offset=0;running(false);
  $('#search-results').replaceChildren();$('#search-prev').hidden=true;$('#search-next').hidden=true;$('#search-page').textContent='';message('Starter søgning…');
  try{const data=await post('/api/search',{pattern:$('#search-query').value,plugin:$('#search-engine').value});token=data.token;await poll(version);}
  catch(e){fail(e);message('Søgningen kunne ikke startes.');}finally{loading=false;$('#search-submit').disabled=false;}
 };
 $('#search-stop').onclick=async()=>{const job=token;$('#search-stop').disabled=true;try{await post('/api/search/'+job,{action:'stop'});await poll();}catch(e){fail(e);}finally{$('#search-stop').disabled=false;}};
 $('#search-prev').onclick=()=>{offset=Math.max(0,offset-50);poll();};
 $('#search-next').onclick=()=>{offset+=50;poll();};
 function enter(){if(location.hash==='#search'&&!loaded)engines().catch(fail);}
 window.addEventListener('hashchange',enter);enter();
})();
