(() => {
 let choices=[],bufferWithoutFlix=false;
 function updateBuffer(){
  const flix=$('#streaming-enabled').checked;
  $('#streaming-buffer').disabled=flix;
  $('#streaming-buffer').checked=flix||bufferWithoutFlix;
  $('#streaming-move-retained').disabled=!flix;
  $('#streaming-mode').textContent=flix?'FjordFlix er slået til: buffer er altid slået til. Færdige filer, der skal beholdes, flyttes til biblioteket.':bufferWithoutFlix?'FjordFlix er slået fra. Buffer er slået til for nye downloads.':'Fra: nye downloads skriver direkte til deres endelige mappe uden buffer eller efterfølgende flytning.';
 }
 function render(data){
  $('#streaming-enabled').checked=data.enabled;
  $('#streaming-move-retained').checked=!!data.move_retained;
  bufferWithoutFlix=data.buffer_when_disabled??(!data.enabled&&!!data.buffer_enabled);
  updateBuffer();
  $('#streaming-link-status').textContent=data.connected?'Forbundet mappe: '+data.host_path+' → '+data.library_path:'Ingen fælles mappe forbundet til den aktuelle downloadplacering.';
 }
 $('#streaming-enabled').onchange=updateBuffer;
 $('#streaming-buffer').onchange=()=>{bufferWithoutFlix=$('#streaming-buffer').checked;updateBuffer();};
 async function load(){
  if(location.hash!=='#streaming')return;
  $('#streaming-error').hidden=true;
  try{render(await api('/api/streaming'));}catch(e){error('#streaming-error',e);}
 }
 $('#streaming-form').onsubmit=async e=>{
  e.preventDefault();const button=$('#streaming-save');button.disabled=true;$('#streaming-error').hidden=true;
  try{render(await api('/api/streaming',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled:$('#streaming-enabled').checked,buffer_enabled:bufferWithoutFlix,move_retained:$('#streaming-move-retained').checked})}));toast('Streamingvalget er gemt.');}
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
  try{render(await api('/api/streaming/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({library_id:$('#streaming-library').value})}));window.dispatchEvent(new Event('storage-changed'));toast('FjordFlix er forbundet. Streaming er slået til for nye downloads.');}
  catch(e){error('#streaming-error',e);}finally{button.disabled=false;}
 };
 window.addEventListener('hashchange',load);load();
})();
