let rssFeeds=[],rssRoot='',rssBusy=false,rssLoading=false,rssTrackerGeneration=0;
const rssBadgeNames={freeleech:'100 % Freeleech',double_upload:'Double upload',featured:'Featured',internal:'Internal',refundable:'Refundable'};
function selectedRssBadges(){return [...document.querySelectorAll('[name=rss-badge]:checked')].map(e=>e.value);}
function updateRssBadges(){
 const required=selectedRssBadges().length>0;
 $('#rss-tracker-label').hidden=!required;$('#rss-tracker').required=required;
}
async function loadRssTrackers(saved=''){
 const generation=++rssTrackerGeneration;const select=$('#rss-tracker');select.replaceChildren();
 if(saved){const option=node('option','','Gemt tracker');option.value=saved;select.append(option);}
 try{
  const data=await api('/api/trackers');if(generation!==rssTrackerGeneration)return;
  select.replaceChildren(node('option','','Vælg tracker'));select.firstChild.value='';
  for(const tracker of data.trackers){const option=node('option','',tracker.name+(tracker.badge_ready?'':' — API afventer'));option.value=tracker.id;select.append(option);}
  if(saved&&!data.trackers.some(t=>t.id===saved)){const option=node('option','','Gemt tracker — API utilgængelig');option.value=saved;select.append(option);}
  select.value=saved||(data.trackers.length===1?data.trackers[0].id:'');
  $('#rss-badge-api-status').textContent=data.trackers.some(t=>t.badge_ready)?'Valgte badges kontrolleres via trackerens API før download.':'Tilføj en tracker med aktiv API-adgang under Trackere for at hente automatisk med badgekrav.';
 }catch(e){if(generation===rssTrackerGeneration)$('#rss-badge-api-status').textContent='Trackerens API-status kunne ikke hentes. Badgekravene bevares.';}
}
function updateRssPath(){ $('#rss-path').textContent='Gemmes i '+rssRoot+($('#rss-folder').value.trim()?'/'+$('#rss-folder').value.trim():''); }
function rssLocalDate(value){
 const date=new Date(value),pad=n=>String(n).padStart(2,'0');
 return `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}
function updateRssStart(){
 const choice=$('#rss-start').value;
 $('#rss-start-date-label').hidden=choice==='all';$('#rss-start-date').required=choice!=='all';
 if(choice!=='custom'&&choice!=='all')$('#rss-start-date').value=rssLocalDate(Date.now()-Number(choice)*86400000);
 $('#rss-start-date').readOnly=choice!=='custom';
}
function resetRssForm(){
 $('#rss-form').reset();$('#rss-id').value='';$('#rss-url').required=true;
 $('#rss-url').placeholder='https://tracker.example/rss?...';$('#rss-form-title').textContent='Tilføj RSS-feed';
 $('#rss-delete-notice').hidden=true;$('#rss-error').hidden=true;updateRssPath();updateRssStart();
 rssShowStep(false);
 updateRssBadges();
}
function rssShowStep(seeding){
 $('#rss-dialog').dataset.step=seeding?'seeding':'source';
 $('#rss-source-step').hidden=seeding;$('#rss-seeding-step').hidden=!seeding;
 $('#rss-next').hidden=seeding;$('#rss-save').hidden=!seeding;$('#rss-back').hidden=!seeding;$('#rss-cancel').hidden=seeding;
 $('#rss-form-title').textContent=seeding?'Seeding og filer':($('#rss-id').value?'Rediger RSS-feed':'Tilføj RSS-feed');
 if(seeding){$('#rss-source-summary').textContent='RSS: '+$('#rss-name').value;$('#rss-ratio').focus();}
}
function openRssForm(feed=null){
 resetRssForm();
 if(feed){
  $('#rss-id').value=feed.id;$('#rss-name').value=feed.name;$('#rss-url').required=false;
  $('#rss-url').placeholder='Gemt adresse — indtast kun for at udskifte';$('#rss-folder').value=feed.folder;
  $('#rss-ratio').value=feed.ratio_limit;$('#rss-action').value=feed.ratio_action;$('#rss-enabled').checked=feed.enabled;
  document.querySelectorAll('[name=rss-badge]').forEach(e=>e.checked=(feed.required_badges||[]).includes(e.value));
  $('#rss-start').value=feed.download_from?'custom':'all';
  if(feed.download_from)$('#rss-start-date').value=rssLocalDate(feed.download_from);
  updateRssStart();$('#rss-form-title').textContent='Rediger RSS-feed';$('#rss-delete-notice').hidden=feed.ratio_action!=='delete';
 }
 updateRssPath();updateRssBadges();loadRssTrackers(feed?.tracker_id||'');$('#rss-dialog').showModal();$('#rss-name').focus();
}
function rssFeedCard(feed){
 const card=node('article','tracker-card'),head=node('div','tracker-card-heading');
 head.append(node('h3','',feed.name),node('span','badge'+(feed.status==='active'?' ready':''),{active:'Aktivt',paused:'På pause',pending:'Afventer VPN / synkronisering',error:'Feedfejl'}[feed.status]));
 card.append(head,node('p','muted small',feed.host+' · '+feed.articles+' feedposter'),node('p','torrent-policy','Mappe: '+rssRoot+(feed.folder?'/'+feed.folder:'')+' · Stop-ratio: '+feed.ratio_limit+' eller 49 timers seeding'+' · '+(feed.ratio_action==='delete'?'Slet filer automatisk':'Behold filer')));
 card.append(node('p','torrent-policy',feed.download_from?'Hent fra: '+new Date(feed.download_from).toLocaleString('da-DK'):'Hent alle poster i feedet'));
 if(feed.required_badges?.length)card.append(node('p','torrent-policy','Kræver alle: '+feed.required_badges.map(b=>rssBadgeNames[b]).join(' + ')));
 if(feed.enabled&&feed.download_status)card.append(node('p','muted small',feed.download_status));
 if(feed.status==='error')card.append(node('p','error small','Feedet eller RSS-reglerne kunne ikke indlæses. Kontrollér RSS-adressen og VPN-status.'));
 const actions=node('div','tracker-actions'),edit=node('button','secondary','Rediger'),remove=node('button','quiet','Fjern feed');edit.type=remove.type='button';
 edit.onclick=()=>openRssForm(feed);
 remove.onclick=async()=>{if(!confirm('Fjern '+feed.name+'? Eksisterende torrents og filer bevares.'))return;remove.disabled=true;try{await api('/api/rss/'+feed.id+'/delete',{method:'POST'});await refreshRss();toast('Feedet er fjernet.');}catch(e){toast(e.message);}finally{remove.disabled=false;}};
 actions.append(edit,remove);card.append(actions);return card;
}
async function refreshRss(){if(rssLoading)return;rssLoading=true;try{const result=await api('/api/rss');rssFeeds=result.feeds;rssRoot=result.download_path;updateRssPath();$('#rss-feed-list').replaceChildren(...(rssFeeds.length?rssFeeds.map(rssFeedCard):[node('p','empty','Ingen RSS-feeds tilføjet endnu.')]));}catch(e){$('#rss-feed-list').replaceChildren(node('p','error',e.message));}finally{rssLoading=false;}}
$('#rss-new').onclick=()=>openRssForm();
$('#rss-folder').oninput=updateRssPath;
$('#rss-start').onchange=updateRssStart;
document.querySelectorAll('[name=rss-badge]').forEach(e=>e.onchange=updateRssBadges);
$('#rss-dialog').addEventListener('close',()=>rssTrackerGeneration++);
$('#rss-action').onchange=()=>$('#rss-delete-notice').hidden=$('#rss-action').value!=='delete';
$('#rss-cancel').onclick=()=>$('#rss-dialog').close();
$('#rss-dialog').addEventListener('cancel',e=>{if(rssBusy)e.preventDefault();});
$('#rss-back').onclick=()=>rssShowStep(false);
$('#rss-next').onclick=()=>{
 for(const input of $('#rss-source-step').querySelectorAll('input, select'))if(!input.reportValidity())return;
 rssShowStep(true);
};
$('#rss-form').onsubmit=async e=>{
 e.preventDefault();if($('#rss-seeding-step').hidden){$('#rss-next').click();return;}if(rssBusy)return;rssBusy=true;$('#rss-save').disabled=true;$('#rss-back').disabled=true;$('#rss-dialog .close').disabled=true;$('#rss-error').hidden=true;
 try{
  const start=$('#rss-start').value==='all'?null:new Date($('#rss-start-date').value).toISOString();
  await api('/api/rss',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
   id:$('#rss-id').value,name:$('#rss-name').value,url:$('#rss-url').value,folder:$('#rss-folder').value,
   ratio_limit:$('#rss-ratio').value,ratio_action:$('#rss-action').value,
   download_from:start,enabled:$('#rss-enabled').checked,required_badges:selectedRssBadges(),
   tracker_id:selectedRssBadges().length?$('#rss-tracker').value:''})});
  $('#rss-dialog').close();resetRssForm();await refreshRss();toast('Feedet er gemt. Synkroniseres når VPN og seedbox er klar.');
 }catch(e){error('#rss-error',e);}finally{rssBusy=false;$('#rss-save').disabled=false;$('#rss-back').disabled=false;$('#rss-dialog .close').disabled=false;}
};
refreshRss();setInterval(refreshRss,10000);
