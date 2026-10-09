let rssFeeds=[],rssRoot='',rssBusy=false,rssLoading=false,rssTrackers=[],rssSavedBadges=[],rssSavedMinimum=0,rssSavedTracker='',rssTrackerGeneration=0;
const rssBadgeNames={freeleech:'100 % Freeleech',double_upload:'Double upload',featured:'Featured',internal:'Internal',refundable:'Refundable'};
function updateRssPath(){ $('#rss-path').textContent='Gemmes i '+rssRoot+($('#rss-folder').value.trim()?'/'+$('#rss-folder').value.trim():''); }
function selectedRssBadges(){return [...document.querySelectorAll('[name=rss-badge]:checked')].map(el=>el.value);}
function updateRssBadgeOptions(){
 const ready=rssTrackers.length>0;
 $('#rss-badge-options').hidden=!ready;
 $('#rss-badge-unavailable').hidden=ready;
 $('#rss-tracker').closest('label').hidden=$('#rss-tracker').options.length<=1;
 $('#rss-badge-retained').hidden=ready||(!rssSavedBadges.length&&!rssSavedMinimum);
 $('#rss-badge-retained').textContent='Gemte krav: '+[...rssSavedBadges.map(b=>rssBadgeNames[b]),...(rssSavedMinimum?['Mindst '+rssSavedMinimum+' downloadere']:[])].join(' + ')+'. Kravene bevares, og download er blokeret, indtil API-adgangen er aktiv igen. Du kan stadig sætte feedet på pause.';
}
async function loadRssTrackers(selected=''){
 const generation=++rssTrackerGeneration;
 rssTrackers=[];updateRssBadgeOptions();
 try{
  const data=await api('/api/trackers');
  if(generation!==rssTrackerGeneration)return;
  rssTrackers=data.trackers.filter(t=>t.badge_ready===true);
  const select=$('#rss-tracker');select.replaceChildren();
  for(const t of rssTrackers){const option=node('option','',t.name);option.value=t.id;select.append(option);}
  if(selected&&rssTrackers.some(t=>t.id===selected))select.value=selected;
  else if(selected){const option=node('option','','Gemt tracker — API-adgang ikke aktiv');option.value=selected;select.prepend(option);select.value=selected;}
 }catch(e){if(generation!==rssTrackerGeneration)return;}
 updateRssBadgeOptions();
}
function resetRssForm(){
 $('#rss-form').reset();rssSavedBadges=[];rssSavedMinimum=0;rssSavedTracker='';$('#rss-id').value='';$('#rss-url').required=true;
 $('#rss-url').placeholder='https://tracker.example/rss?...';$('#rss-form-title').textContent='Tilføj RSS-feed';
 $('#rss-delete-notice').hidden=true;$('#rss-error').hidden=true;updateRssPath();
}
function openRssForm(feed=null){
 resetRssForm();
 if(feed){
  $('#rss-id').value=feed.id;$('#rss-name').value=feed.name;$('#rss-url').required=false;
  $('#rss-url').placeholder='Gemt adresse — indtast kun for at udskifte';$('#rss-folder').value=feed.folder;
  $('#rss-ratio').value=feed.ratio_limit;$('#rss-action').value=feed.ratio_action;$('#rss-enabled').checked=feed.enabled;
  $('#rss-include').value=feed.include;$('#rss-form-title').textContent='Rediger RSS-feed';$('#rss-delete-notice').hidden=feed.ratio_action!=='delete';
  rssSavedBadges=feed.required_badges||[];rssSavedTracker=feed.tracker_id||'';
  rssSavedMinimum=feed.min_leechers||0;$('#rss-min-leechers').value=rssSavedMinimum;
  document.querySelectorAll('[name=rss-badge]').forEach(el=>el.checked=rssSavedBadges.includes(el.value));
 }
 updateRssPath();loadRssTrackers(rssSavedTracker);$('#rss-dialog').showModal();$('#rss-name').focus();
}
function rssFeedCard(feed){
 const card=node('article','tracker-card'),head=node('div','tracker-card-heading');
 head.append(node('h3','',feed.name),node('span','badge'+(feed.status==='active'?' ready':''),{active:'Aktivt',paused:'På pause',pending:'Afventer VPN / synkronisering',error:'Feedfejl'}[feed.status]));
 card.append(head,node('p','muted small',feed.host+' · '+feed.articles+' feedposter'),node('p','torrent-policy','Mappe: '+rssRoot+(feed.folder?'/'+feed.folder:'')+' · Stop-ratio: '+feed.ratio_limit+' eller 48 timers seeding'+' · '+(feed.ratio_action==='delete'?'Slet filer automatisk':'Behold filer')));
 if(feed.include)card.append(node('p','muted small','Titelfilter: '+feed.include));
 if(feed.required_badges?.length){
  const badges=node('div','rss-required-badges');badges.append(node('span','muted small','Kræver alle:'));
  feed.required_badges.forEach(b=>badges.append(node('span','benefit-badge',rssBadgeNames[b])));card.append(badges);
 }
 if(feed.min_leechers>0)card.append(node('p','torrent-policy','Mindst '+feed.min_leechers+' downloadere før automatisk download'));
 if(feed.enabled&&(feed.required_badges?.length||feed.min_leechers>0)&&feed.badge_status)card.append(node('p','muted small',feed.badge_status));
 if(feed.status==='error')card.append(node('p','error small','Feedet eller RSS-reglerne kunne ikke indlæses. Kontrollér RSS-adressen og VPN-status.'));
 const actions=node('div','tracker-actions'),edit=node('button','secondary','Rediger'),remove=node('button','quiet','Fjern feed');edit.type=remove.type='button';
 edit.onclick=()=>openRssForm(feed);
 remove.onclick=async()=>{if(!confirm('Fjern '+feed.name+'? Eksisterende torrents og filer bevares.'))return;remove.disabled=true;try{await api('/api/rss/'+feed.id+'/delete',{method:'POST'});await refreshRss();toast('Feedet er fjernet.');}catch(e){toast(e.message);}finally{remove.disabled=false;}};
 actions.append(edit,remove);card.append(actions);return card;
}
async function refreshRss(){if(rssLoading)return;rssLoading=true;try{const result=await api('/api/rss');rssFeeds=result.feeds;rssRoot=result.download_path;updateRssPath();$('#rss-feed-list').replaceChildren(...(rssFeeds.length?rssFeeds.map(rssFeedCard):[node('p','empty','Ingen RSS-feeds tilføjet endnu.')]));}catch(e){$('#rss-feed-list').replaceChildren(node('p','error',e.message));}finally{rssLoading=false;}}
$('#rss-new').onclick=()=>openRssForm();
$('#rss-folder').oninput=updateRssPath;
$('#rss-action').onchange=()=>$('#rss-delete-notice').hidden=$('#rss-action').value!=='delete';
$('#rss-cancel').onclick=()=>$('#rss-dialog').close();
$('#rss-dialog').addEventListener('close',()=>{rssTrackerGeneration++;});
$('#rss-form').onsubmit=async e=>{
 e.preventDefault();if(rssBusy)return;rssBusy=true;$('#rss-save').disabled=true;$('#rss-error').hidden=true;
 try{
  const badges=rssTrackers.length?selectedRssBadges():rssSavedBadges;
  const tracker=rssTrackers.length?$('#rss-tracker').value:rssSavedTracker;
  const minimum=rssTrackers.length?Number($('#rss-min-leechers').value):rssSavedMinimum;
  await api('/api/rss',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
   id:$('#rss-id').value,name:$('#rss-name').value,url:$('#rss-url').value,folder:$('#rss-folder').value,
   ratio_limit:$('#rss-ratio').value,ratio_action:$('#rss-action').value,include:$('#rss-include').value,
   enabled:$('#rss-enabled').checked,required_badges:badges,min_leechers:minimum,tracker_id:badges.length||minimum>0?tracker:''})});
  $('#rss-dialog').close();resetRssForm();await refreshRss();toast('Feedet er gemt. Synkroniseres når VPN og seedbox er klar.');
 }catch(e){error('#rss-error',e);}finally{rssBusy=false;$('#rss-save').disabled=false;}
};
refreshRss();setInterval(refreshRss,10000);
