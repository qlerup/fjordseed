(() => {
 let last;
 function devices(data){
  last=data;
  const list=$('#conversion-devices');list.replaceChildren();
  if(!data.devices.length)list.append(node('p','muted small','Ingen pc’er forbundet endnu.'));
  for(const device of data.devices){
   const row=node('div','storage-summary');
   const info=node('div');info.append(node('strong','',device.name),node('p','muted small',device.online?'Forbundet · GPU klar':device.last_seen?'Offline · sidst set '+new Date(device.last_seen*1000).toLocaleString('da-DK'):'Afventer første forbindelse'));
   const revoke=node('button','secondary','Fjern adgang');revoke.type='button';
   revoke.onclick=async()=>{revoke.disabled=true;try{await api('/api/conversion/devices/'+device.id+'/revoke',{method:'POST'});await load(false);toast('Pc-tokenet er tilbagekaldt.');}catch(e){error('#conversion-settings-error',e);}finally{revoke.disabled=false;}};
   row.append(info,revoke);list.append(row);
  }
  workerStatus();
 }
 function workerStatus(){
  if(!last)return;
  const pc=$('#conversion-target').value==='pc',online=last.devices.filter(d=>d.online).length;
  $('#conversion-worker-status').textContent=pc?(online?online+' pc-forbindelse(r) er klar. Originalen sendes til pc’en, når downloadet er færdigt.':'Ingen pc er klar endnu. Åbn pc-programmet og forbind det med et token nedenfor.'):(last.conversion_error||(last.conversion_configured?'Serverens GPU-service er installeret.':'Serverens GPU-service er ikke installeret. Vælg en pc, eller tilføj GPU-servicen gennem FjordHub.'));
 }
 async function load(form=true){
  if(location.hash!=='#conversion')return;
  try{
   const data=await api('/api/conversion');
   if(form){$('#conversion-enabled').checked=!!data.conversion_enabled;$('#conversion-bitrate').value=String(data.conversion_bitrate||20);$('#conversion-target').value=data.conversion_target||'server';}
   devices(data);$('#conversion-server-address').value=location.origin;
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
  try{const data=await api('/api/conversion/devices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('#conversion-device-name').value})});$('#conversion-token-secret').value=data.token;$('#conversion-token-result').hidden=false;await load(false);$('#conversion-token-secret').focus();$('#conversion-token-secret').select();}
  catch(e){error('#conversion-settings-error',e);}finally{button.disabled=false;}
 };
 window.addEventListener('hashchange',()=>load());setInterval(()=>load(false),5000);load();
})();
