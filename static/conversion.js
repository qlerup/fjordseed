let conversionSettings={conversion_enabled:false,conversion_bitrate:30};
function updateConversionChoice(prefix){
 const input=$('#'+prefix+'-convert');
 const enabled=conversionSettings.conversion_enabled;
 // Existing RSS preferences remain visible and editable when globally disabled.
 input.disabled=!enabled&&!input.checked;
 $('#'+prefix+'-conversion-hint').textContent=enabled?
  'GPU · HEVC/MKV · '+conversionSettings.conversion_bitrate+' Mbps video. Lyd og undertekster bevares.':
  'Konvertering er slået fra under Indstillinger → Konvertering. Feeds med dette valg venter med nye downloads.';
 $('#'+prefix+'-conversion-policy').hidden=!input.checked;
 $('#'+prefix+'-normal-seeding').hidden=input.checked;
 for(const field of $('#'+prefix+'-normal-seeding').querySelectorAll('input,select'))field.disabled=input.checked;
 if(!input.checked)updateSeedingFields(prefix);
}
async function loadConversionChoices(){
 try{conversionSettings=await api('/api/streaming');}
 catch(e){for(const prefix of ['ratio','rss'])$('#'+prefix+'-conversion-hint').textContent=e.message;return;}
 for(const prefix of ['ratio','rss'])updateConversionChoice(prefix);
}
for(const prefix of ['ratio','rss'])$('#'+prefix+'-convert').addEventListener('change',()=>updateConversionChoice(prefix));
window.addEventListener('conversion-settings-changed',loadConversionChoices);
for(const id of ['add-dialog','ratio-dialog'])new MutationObserver(()=>{
 if($('#'+id).open)loadConversionChoices();
}).observe($('#'+id),{attributes:true,attributeFilter:['open']});
loadConversionChoices();
