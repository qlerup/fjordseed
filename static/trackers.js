let trackerData=[],trackerSaving=false,trackerRefreshing=false;
const trackerNumber=value=>typeof value==='number'?value.toLocaleString('da-DK',{maximumFractionDigits:2}):'—';
const trackerBytes=value=>{
 if(typeof value!=='number'||!Number.isFinite(value)||value<0)return '—';
 const units=['B','KiB','MiB','GiB','TiB'];let index=0;
 while(value>=1024&&index<units.length-1){value/=1024;index++;}
 return value.toLocaleString('da-DK',{minimumFractionDigits:index?2:0,maximumFractionDigits:index?2:0})+' '+units[index];
};
function trackerCard(tracker,manage=false){
 const card=node('article','tracker-card'),head=node('div','tracker-card-heading'),title=node('div');
 title.append(node('h3','',tracker.name));
 if(tracker.username)title.append(node('p','muted small',tracker.username));
 head.append(title,node('span','badge'+(tracker.status==='ok'?' ready':''),tracker.status==='ok'?'Forbundet':tracker.status==='error'?'Forbindelsesfejl':'Henter data'));
 card.append(head);
 if(tracker.status==='error')card.append(node('p','error small',tracker.error));
 if(tracker.stats){
  const stats=node('div','tracker-stats');
  for(const [label,field,format] of [['UPLOAD','uploaded',trackerBytes],['DOWNLOAD','downloaded',trackerBytes],['RATIO','ratio',trackerNumber],['BUFFER','buffer',trackerBytes],['SEEDING','seeding',trackerNumber],['DOWNLOADER','leeching',trackerNumber],['SHARDS','seedbonus',trackerNumber],['HIT-AND-RUNS','hit_and_runs',trackerNumber],['ADVARSLER','warnings',trackerNumber],['SEEDING-STØRRELSE','seeding_size',trackerBytes],['UPLOADS','total_uploads',trackerNumber]]){
   const item=node('div');item.append(node('span','',label),node('strong','',format(tracker.stats[field])));stats.append(item);
  }
  card.append(stats);
  for(const event of tracker.events||[]){const end=new Date(event.ends_at);card.append(node('p','tracker-event',event.title+(Number.isNaN(end.getTime())?'':' · Slutter '+end.toLocaleString('da-DK',{dateStyle:'short',timeStyle:'short'}))));}
 }
 if(tracker.updated_at)card.append(node('p','muted small',(tracker.status==='ok'?'Opdateret ':'Senest hentede tal fra ')+new Date(tracker.updated_at*1000).toLocaleString('da-DK',{dateStyle:'short',timeStyle:'short'})));
 if(manage){
  const actions=node('div','tracker-actions'),edit=node('button','secondary','Rediger'),remove=node('button','quiet','Fjern tracker');
  edit.type=remove.type='button';edit.onclick=()=>{
   $('#tracker-id').value=tracker.id;$('#tracker-name').value=tracker.name;$('#tracker-provider').value=tracker.provider;$('#tracker-key').value='';$('#tracker-key').required=false;$('#tracker-key').placeholder='Gemt nøgle — indtast kun for at udskifte';$('#tracker-cancel').hidden=false;$('#tracker-save').textContent='Gem ændringer';$('#tracker-form-error').hidden=true;$('#tracker-name').focus();
  };
  remove.onclick=async()=>{
   if(!confirm('Fjern '+tracker.name+' fra FjordSeed? Torrents og downloadede filer bevares.'))return;
   remove.disabled=true;try{await api('/api/trackers/'+tracker.id+'/delete',{method:'POST'});if($('#tracker-id').value===tracker.id)resetTrackerForm();await refreshTrackers();toast('Trackeren er fjernet.');}catch(e){toast(e.message);}finally{remove.disabled=false;}
  };
  actions.append(edit,remove);card.append(actions);
 }
 return card;
}
function resetTrackerForm(){
 $('#tracker-form').reset();$('#tracker-id').value='';$('#tracker-key').value='';$('#tracker-key').required=true;$('#tracker-key').placeholder='Indsæt API-nøgle med adgang til kontodata';$('#tracker-cancel').hidden=true;$('#tracker-save').textContent='Gem tracker';$('#tracker-form-error').hidden=true;
}
async function refreshTrackers(){
 if(trackerRefreshing)return;trackerRefreshing=true;
 try{
  const result=await api('/api/trackers');trackerData=result.trackers;
  $('#tracker-overview').hidden=!trackerData.length;
  $('#tracker-account-list').replaceChildren(...trackerData.map(t=>trackerCard(t)));
  $('#tracker-settings-list').replaceChildren(...(trackerData.length?trackerData.map(t=>trackerCard(t,true)):[node('p','empty','Du har ikke tilføjet en tracker endnu.')]));
 }catch(e){
  $('#tracker-settings-list').replaceChildren(node('p','error',e.message));
  if(trackerData.length)$('#tracker-account-list').replaceChildren(node('p','error','Trackerstatistik kunne ikke hentes. Prøver igen automatisk.'));
 }finally{trackerRefreshing=false;}
}
$('#tracker-cancel').onclick=resetTrackerForm;
$('#tracker-form').onsubmit=async e=>{
 e.preventDefault();if(trackerSaving)return;trackerSaving=true;$('#tracker-save').disabled=true;$('#tracker-form-error').hidden=true;
 try{await api('/api/trackers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:$('#tracker-id').value,provider:$('#tracker-provider').value,name:$('#tracker-name').value,api_key:$('#tracker-key').value})});resetTrackerForm();toast('Trackeren er gemt. Henter kontodata.');await refreshTrackers();}
 catch(e){error('#tracker-form-error',e);}
 finally{trackerSaving=false;$('#tracker-save').disabled=false;}
};
refreshTrackers();setInterval(refreshTrackers,10000);
