(() => {
 let choices=[];
 function render(data){
  $('#streaming-enabled').checked=data.enabled;
  $('#streaming-mode').textContent=data.enabled?'Til: nye downloads starter i bufferen. Færdige filer, der skal beholdes, flyttes til biblioteket.':'Fra: nye downloads skriver direkte til deres endelige mappe uden buffer eller efterfølgende flytning.';
  $('#streaming-link-status').textContent=data.connected?'Forbundet mappe: '+data.host_path+' → '+data.library_path:'Ingen fælles mappe forbundet til den aktuelle downloadplacering.';
 }
 async function load(){
  if(location.hash!=='#streaming')return;
  $('#streaming-error').hidden=true;
  try{render(await api('/api/streaming'));}catch(e){error('#streaming-error',e);}
 }
 $('#streaming-form').onsubmit=async e=>{
  e.preventDefault();const button=$('#streaming-save');button.disabled=true;$('#streaming-error').hidden=true;
  try{render(await api('/api/streaming',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:$('#streaming-enabled').checked})}));toast('Streamingvalget er gemt. Gælder nye downloads.');}
  catch(e){error('#streaming-error',e);}finally{button.disabled=false;}
 };
 $('#streaming-find').onclick=async()=>{
  const button=$('#streaming-find');button.disabled=true;$('#streaming-error').hidden=true;$('#streaming-folders').hidden=true;
  try{
   const data=await api('/api/streaming/flix');choices=data.choices||[];
   if(!choices.length)throw Error('Ingen tilgængelig biblioteksmappe fundet. Tilføj en mappe under /mnt, /media eller /srv i FjordFlix først.');
   const select=$('#streaming-library');select.replaceChildren();
   for(const choice of choices){const option=node('option','',choice.path+(choice.current?' · Aktuel downloadmappe':''));option.value=choice.id;select.append(option);}
   $('#streaming-folders').hidden=false;select.onchange=()=>{
    const choice=choices.find(c=>c.id===select.value);$('#streaming-folder-help').textContent=choice?'FjordFlix læser: '+choice.library_path:'';
   };select.onchange();
  }catch(e){error('#streaming-error',e);}finally{button.disabled=false;}
 };
 $('#streaming-connect').onclick=async()=>{
  const button=$('#streaming-connect');button.disabled=true;$('#streaming-error').hidden=true;
  try{render(await api('/api/streaming/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({library_id:$('#streaming-library').value})}));toast('FjordFlix er forbundet. Streaming er slået til for nye downloads.');}
  catch(e){error('#streaming-error',e);}finally{button.disabled=false;}
 };
 window.addEventListener('hashchange',load);load();
})();
