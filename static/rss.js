let rssFeeds=[],rssRoot='',rssBusy=false,rssLoading=false,rssTrackerGeneration=0;
let rssRefreshPromise;
let rssHistoryGeneration=0;
function rssHistoryMetric(label,value){
 const cell=node('div','rss-history-metric');cell.append(node('dt','muted small',label),node('dd','',typeof value==='number'&&Number.isFinite(value)?size(value):'Ukendt'));return cell;
}
function rssHistoryFile(item){
 const row=node('details','rss-history-file'),summary=node('summary');
 summary.append(node('span','',item.title),node('span','rss-history-credit',size(item.credited_uploaded)));
 row.append(summary);
 const metrics=node('dl','rss-history-metrics');
 metrics.append(rssHistoryMetric('Upload',item.uploaded),rssHistoryMetric('Krediteret upload',item.upload_credit_pending&&!item.credited_uploaded?null:item.credited_uploaded),rssHistoryMetric('Download',item.downloaded),rssHistoryMetric('Krediteret download',item.download_credit_incomplete||item.download_credit_pending?null:item.credited_downloaded));
 row.append(metrics);
 const facts=[];
 if(item.added_at)facts.push('Registreret '+new Date(item.added_at*1000).toLocaleString('da-DK'));
 if(typeof item.progress==='number')facts.push('Hentet '+Math.round(item.progress*100)+' %');
 if(item.size)facts.push('Torrentstørrelse '+size(item.size));
 row.append(node('p','muted small',facts.join(' · ')));
 const flags=item.tracker_flags,labels=[];
 if(flags){
  if(flags.green_until>item.traffic_updated_at)labels.push('Green: halv uploadkredit i de første 24 timer');
  if(flags.double_upload===true)labels.push('Dobbelt upload: ×2');
  if(typeof flags.freeleech==='number')labels.push(flags.freeleech+' % freeleech');
  if(labels.length)row.append(node('p','rss-history-flags small','Ved seneste måling: '+labels.join(' · ')));
 }
 if(item.upload_credit_pending||item.download_credit_pending)row.append(node('p','muted small','Afventer bekræftede trackerflag for den seneste trafik. Målingerne er gemt.'));
 if(item.upload_credit_incomplete||item.download_credit_incomplete||item.uploaded===undefined||item.downloaded===undefined)row.append(node('p','muted small','Ældre målinger eller flag mangler. De kan ikke genskabes præcist ud fra dagens flag. Nye målinger gemmes løbende.'));
 row.append(node('p','muted small','Kredittal er beregnede ud fra de kendte trackerfordele. Ukendt betyder, at historiske målinger eller bekræftede fordele mangler.'));
 if(item.estimated||item.tracker_credit_estimated)row.append(node('p','muted small','Kredittal indeholder estimater eller bevaret ældre kredit.'));
 return row;
}
async function openRssHistory(feed){
 const generation=++rssHistoryGeneration;
 const list=$('#rss-history-list'),status=$('#rss-history-status');
 $('#rss-history-title').textContent='Downloadhistorik · '+feed.name;
 list.replaceChildren();status.textContent='Henter historik…';
 if(!$('#rss-history-dialog').open)$('#rss-history-dialog').showModal();
 try{
  const result=await api('/api/rss/'+feed.id+'/history/groups');
  if(generation!==rssHistoryGeneration)return;
  status.textContent=result.count?result.count+' torrents · '+result.groups.length+' grupper':'Ingen hentede titler registreret endnu.';
  let visible=0;
  function more(){
   const batch=result.groups.slice(visible,visible+40);visible+=batch.length;
   for(const group of batch){
    const card=node('li','rss-history-group'),head=node('div','rss-history-group-head'),details=node('details'),summary=node('summary');
    summary.append(node('strong','',group.title),node('span','muted small',group.downloads.length+' torrents'));
    details.append(summary);
    const files=node('div','rss-history-files');let shown=0;
    const moreFiles=node('button','quiet','Vis flere filer');moreFiles.type='button';
    function appendFiles(){for(const item of group.downloads.slice(shown,shown+40))files.append(rssHistoryFile(item));shown+=40;moreFiles.hidden=shown>=group.downloads.length;}
    details.addEventListener('toggle',()=>{if(details.open&&!shown)appendFiles();});moreFiles.onclick=appendFiles;
    details.append(files,moreFiles);moreFiles.hidden=true;
    const exclude=node('button','secondary rss-history-exclude',group.excluded?'Udelukket':'Udeluk');exclude.type='button';exclude.disabled=group.excluded;
    exclude.title='Føj “'+group.exclude_title+'” fra torrentnavnet til feedets udeluk-filter. Eksisterende downloads bevares.';
    exclude.onclick=async()=>{
     exclude.disabled=true;
     try{await api('/api/rss/'+feed.id+'/history/exclude',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({group:group.key})});exclude.textContent='Udelukket';toast('Udeluk-filter tilføjet: '+group.exclude_title);refreshRss();}
     catch(e){exclude.disabled=false;toast(e.message);}
    };
    head.append(details,exclude);card.append(head);list.append(card);
   }
   next.hidden=visible>=result.groups.length;
  }
  const next=node('button','secondary','Vis flere grupper');next.type='button';next.onclick=more;
  more();list.querySelector('[data-more-groups]')?.remove();next.dataset.moreGroups='true';list.append(next);
  $('#rss-history-dialog').addEventListener('close',()=>next.remove(),{once:true});
 }catch(e){if(generation===rssHistoryGeneration)status.textContent=e.message;}
}
const expandedRssFeeds=new Set(),rssToggleBusy=new Set();
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
const rssSizeUnits={MB:1024**2,GB:1024**3,TB:1024**4};
function rssMaxSize(){
 const input=$('#rss-max-size');input.setCustomValidity('');
 if(!input.value.trim())return null;
 const bytes=Math.floor(Number(input.value)*rssSizeUnits[$('#rss-size-unit').value]);
 if(!Number.isSafeInteger(bytes)||bytes<1){input.setCustomValidity('Angiv en størrelse større end nul, eller lad feltet være tomt.');throw new Error(input.validationMessage);}
 return bytes;
}
function showRssMaxSize(bytes){
 $('#rss-max-size').setCustomValidity('');
 if(!bytes){$('#rss-max-size').value='';$('#rss-size-unit').value='GB';return;}
 const unit=bytes>=rssSizeUnits.TB?'TB':bytes>=rssSizeUnits.GB?'GB':'MB';
 $('#rss-size-unit').value=unit;$('#rss-max-size').value=String(bytes/rssSizeUnits[unit]);
}
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
 rssTitleFilters={include:[],exclude:[]};updateRssFilterSummary();
 $('#rss-form').reset();$('#rss-id').value='';$('#rss-url').required=true;$('#rss-url-status').hidden=true;
 showRssMaxSize(null);
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
 if(seeding){$('#rss-source-summary').textContent='RSS: '+$('#rss-name').value;updateSeedingFields('rss');$('#rss-action').focus();}
}
function openRssForm(feed=null){
 resetRssForm();
 if(feed){
  rssTitleFilters={include:[...(feed.title_include||[])],exclude:[...(feed.title_exclude||[])]};updateRssFilterSummary();
  $('#rss-id').value=feed.id;$('#rss-name').value=feed.name;$('#rss-url').required=false;$('#rss-url-status').hidden=false;
  showRssMaxSize(feed.max_size_bytes);
  $('#rss-url').placeholder='Gemt adresse — indtast kun for at udskifte';$('#rss-folder').value=feed.folder;
  $('#rss-ratio').value=feed.ratio_limit;$('#rss-action').value=feed.ratio_action;$('#rss-enabled').checked=feed.enabled;
  document.querySelectorAll('[name=rss-badge]').forEach(e=>e.checked=(feed.required_badges||[]).includes(e.value));
  $('#rss-start').value=feed.download_from?'custom':'all';
  if(feed.download_from)$('#rss-start-date').value=rssLocalDate(feed.download_from);
  updateRssStart();$('#rss-form-title').textContent='Rediger RSS-feed';$('#rss-delete-notice').hidden=['keep','stop_keep'].includes(feed.ratio_action);
 }
 updateRssPath();updateRssBadges();loadRssTrackers(feed?.tracker_id||'');$('#rss-dialog').showModal();$('#rss-name').focus();
}
function rssFeedCard(feed){
 const card=node('article','tracker-card rss-feed-card'),head=node('div','tracker-card-heading');
 const heading=node('h3'),titleToggle=node('button','torrent-title-toggle');titleToggle.type='button';
 const arrow=node('span','torrent-chevron');arrow.setAttribute('aria-hidden','true');
 titleToggle.append(arrow,node('span','torrent-name',feed.name));heading.append(titleToggle);
 const controls=node('div','rss-heading-controls'),toggle=node('button','secondary torrent-toggle');toggle.type='button';
 controls.append(node('span','badge'+(feed.status==='active'?' ready':''),{active:'Aktivt',paused:'På pause',pending:'Afventer VPN / synkronisering',error:'Feedfejl'}[feed.status]),toggle);
 const enabledToggle=node('button','rss-enabled-toggle');enabledToggle.type='button';
 enabledToggle.setAttribute('role','switch');enabledToggle.setAttribute('aria-checked',String(feed.enabled));
 enabledToggle.setAttribute('aria-label','Automatisk hentning for '+feed.name);
 enabledToggle.title='Slå automatisk hentning til eller fra. Eksisterende torrents fortsætter.';
 enabledToggle.dataset.rssToggle=feed.id;enabledToggle.dataset.rssToggleControl='enabled';
 const switchTrack=node('span','rss-switch-track');switchTrack.setAttribute('aria-hidden','true');
 enabledToggle.append(switchTrack,node('span','',rssToggleBusy.has(feed.id)?'Gemmer…':feed.enabled?'Tændt':'Slukket'));
 enabledToggle.disabled=rssToggleBusy.has(feed.id);controls.prepend(enabledToggle);
 enabledToggle.onclick=async()=>{
  if(rssToggleBusy.has(feed.id))return;
  const enabled=!feed.enabled,restoreFocus=document.activeElement===enabledToggle;rssToggleBusy.add(feed.id);enabledToggle.disabled=true;edit.disabled=remove.disabled=true;
  enabledToggle.lastChild.textContent='Gemmer…';
  try{
   await api('/api/rss/'+feed.id+'/enabled',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})});
   feed.enabled=enabled;enabledToggle.setAttribute('aria-checked',String(enabled));
   toast(enabled?'Feedet er tændt. Nye poster hentes, når VPN og seedbox er klar.':'Feedet er slukket. Eksisterende torrents fortsætter.');
  }catch(e){toast(e.message);}
  finally{
   await rssRefreshPromise;rssToggleBusy.delete(feed.id);
   enabledToggle.disabled=false;edit.disabled=remove.disabled=false;
   enabledToggle.lastChild.textContent=feed.enabled?'Tændt':'Slukket';
   if(restoreFocus&&document.activeElement===document.body)enabledToggle.focus({preventScroll:true});
   await refreshRss();
  }
 };

 head.append(heading,controls);
 const panel=node('div','rss-feed-details');panel.id='rss-feed-details-'+feed.id;
 for(const [button,control] of [[titleToggle,'title'],[toggle,'details']]){button.dataset.rssToggle=feed.id;button.dataset.rssToggleControl=control;button.setAttribute('aria-controls',panel.id);}
 function updateExpanded(){const expanded=expandedRssFeeds.has(feed.id);panel.hidden=!expanded;card.classList.toggle('is-expanded',expanded);toggle.textContent=expanded?'Skjul detaljer':'Vis detaljer';for(const button of [toggle]){button.setAttribute('aria-expanded',String(expanded));button.setAttribute('aria-label',toggle.textContent+' for '+feed.name);}}
 toggle.onclick=()=>{if(expandedRssFeeds.has(feed.id))expandedRssFeeds.delete(feed.id);else expandedRssFeeds.add(feed.id);updateExpanded();};titleToggle.onclick=()=>openRssHistory(feed);titleToggle.setAttribute('aria-label','Downloadhistorik for '+feed.name);titleToggle.setAttribute('aria-haspopup','dialog');
 card.append(head,node('p','muted small',feed.host+' · '+feed.articles+' feedposter'));
 const upload=node('div','rss-feed-upload'),uploadLabel=node('span','muted small','Krediteret upload i alt');
 const hasUpload=typeof feed.credited_uploaded==='number'&&Number.isFinite(feed.credited_uploaded)&&feed.credited_uploaded>=0;
 upload.append(uploadLabel,node('strong','rss-feed-upload-value',hasUpload?size(feed.credited_uploaded):'Afventer uploadtal'));
 if(feed.credit_estimated)upload.append(node('span','muted small','Beregnet konservativt'));
 upload.title='Samlet beregnet kredit fra feedets torrents, inkl. Green-periodens halve kredit. Gemmes også efter sletning af torrents. Tidligere slettede torrents kan mangle i historikken.';
 card.append(upload);
 panel.append(node('p','torrent-policy','Mappe: '+rssRoot+(feed.folder?'/'+feed.folder:'')+(feed.ratio_action==='stop_keep'?' · Stop seeding efter download og behold filerne':feed.ratio_action==='automatic'?' · Automatisk: optimer ratio og slet · målratio '+feed.ratio_limit+' eller 49 timers seedtid':feed.ratio_action!=='keep'?' · Slet ved ratio '+feed.ratio_limit+(feed.ratio_action==='delete_ratio'?' uden tidsgrænse':' eller 49 timers seeding'):' · Behold filer og seed uden grænse')));
 panel.append(node('p','torrent-policy',feed.download_from?'Hent fra: '+new Date(feed.download_from).toLocaleString('da-DK'):'Hent alle poster i feedet'));
 if(feed.max_size_bytes)panel.append(node('p','torrent-policy','Maksimal torrentstørrelse: '+size(feed.max_size_bytes)));
 if(feed.required_badges?.length)panel.append(node('p','torrent-policy','Kræver alle: '+feed.required_badges.map(b=>rssBadgeNames[b]).join(' + ')));
 if(feed.title_include?.length)panel.append(node('p','torrent-policy','Kig efter: '+feed.title_include.join(', ')));
 if(feed.title_exclude?.length)panel.append(node('p','torrent-policy','Undgå: '+feed.title_exclude.join(', ')));
 if(feed.enabled&&feed.download_status)panel.append(node('p','muted small',feed.download_status));
 if(feed.status==='error')panel.append(node('p','error small','Feedet eller RSS-reglerne kunne ikke indlæses. Kontrollér RSS-adressen og VPN-status.'));
 const history=node('button','secondary','Downloadhistorik');history.type='button';history.onclick=()=>openRssHistory(feed);panel.append(history);
 const actions=node('div','tracker-actions'),edit=node('button','secondary','Rediger'),remove=node('button','quiet','Fjern feed');edit.type=remove.type='button';
 edit.disabled=remove.disabled=rssToggleBusy.has(feed.id);
 edit.onclick=()=>openRssForm(feed);
 remove.onclick=async()=>{if(!confirm('Fjern '+feed.name+'? Eksisterende torrents og filer bevares.'))return;remove.disabled=true;try{await api('/api/rss/'+feed.id+'/delete',{method:'POST'});await refreshRss();toast('Feedet er fjernet.');}catch(e){toast(e.message);}finally{remove.disabled=false;}};
 actions.append(edit,remove);card.append(panel,actions);updateExpanded();return card;
}
async function refreshRss(){
 if(rssToggleBusy.size)return;
 if(rssLoading)return rssRefreshPromise;
 rssLoading=true;
 rssRefreshPromise=(async()=>{
  try{
   const result=await api('/api/rss');
   if(rssToggleBusy.size)return;
   rssFeeds=result.feeds;rssRoot=result.download_path;updateRssPath();
   const summary=rssFeeds.length+' feeds · '+rssFeeds.filter(feed=>feed.enabled).length+' tændt';
   $('#rss-feed-summary').textContent=summary;
   $('#rss-feeds-summary').textContent=summary;
   const uploads=rssFeeds.map(feed=>feed.own_credited_uploaded??feed.credited_uploaded);
   const hasTotals=uploads.every(value=>typeof value==='number'&&Number.isFinite(value)&&value>=0);
   $('#rss-feeds-upload-total').textContent=typeof result.credited_uploaded_total==='number'?size(result.credited_uploaded_total):hasTotals?size(uploads.reduce((total,value)=>total+value,0)):'Afventer uploadtal';
   const focused=document.activeElement?.dataset,key=focused?.rssToggle,control=focused?.rssToggleControl;
   $('#rss-feed-list').replaceChildren(...(rssFeeds.length?rssFeeds.map(rssFeedCard):[node('p','empty','Ingen RSS-feeds tilføjet endnu.')]));
   if(key)for(const button of document.querySelectorAll('[data-rss-toggle]'))if(button.dataset.rssToggle===key&&button.dataset.rssToggleControl===control){button.focus({preventScroll:true});break;}
  }catch(e){if(!rssToggleBusy.size)$('#rss-feed-list').replaceChildren(node('p','error',e.message));}
  finally{rssLoading=false;}
 })();
 return rssRefreshPromise;
}

$('#rss-new').onclick=()=>openRssForm();
$('#rss-feeds-add').onclick=()=>openRssForm();
$('#rss-manage').onclick=()=>{$('#rss-feeds-dialog').showModal();refreshRss();};
$('#rss-history-dialog').addEventListener('close',()=>rssHistoryGeneration++);
$('#rss-folder').oninput=updateRssPath;
$('#rss-start').onchange=updateRssStart;
$('#rss-max-size').oninput=()=>$('#rss-max-size').setCustomValidity('');
$('#rss-size-unit').onchange=()=>$('#rss-max-size').setCustomValidity('');
document.querySelectorAll('[name=rss-badge]').forEach(e=>e.onchange=updateRssBadges);
$('#rss-dialog').addEventListener('close',()=>{rssTrackerGeneration++;if($('#rss-filter-dialog').open)$('#rss-filter-dialog').close();});
$('#rss-action').onchange=()=>updateSeedingFields('rss');
updateSeedingFields('rss');
$('#rss-cancel').onclick=()=>$('#rss-dialog').close();
$('#rss-dialog').addEventListener('cancel',e=>{if(rssBusy)e.preventDefault();});
$('#rss-back').onclick=()=>rssShowStep(false);
$('#rss-next').onclick=()=>{
 try{rssMaxSize();}catch{ $('#rss-max-size').reportValidity();return; }
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
   max_size_bytes:rssMaxSize(),
   title_include:rssTitleFilters.include,title_exclude:rssTitleFilters.exclude,
   tracker_id:selectedRssBadges().length?$('#rss-tracker').value:''})});
  $('#rss-dialog').close();resetRssForm();await refreshRss();toast('Feedet er gemt. Synkroniseres når VPN og seedbox er klar.');
 }catch(e){error('#rss-error',e);}finally{rssBusy=false;$('#rss-save').disabled=false;$('#rss-back').disabled=false;$('#rss-dialog .close').disabled=false;}
};
refreshRss();setInterval(refreshRss,10000);
