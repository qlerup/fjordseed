let rssFeeds=[],rssRoot='',rssBusy=false,rssLoading=false;
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
}
function openRssForm(feed=null){
 resetRssForm();
 if(feed){
  $('#rss-id').value=feed.id;$('#rss-name').value=feed.name;$('#rss-url').required=false;
  $('#rss-url').placeholder='Gemt adresse — indtast kun for at udskifte';$('#rss-folder').value=feed.folder;
  $('#rss-ratio').value=feed.ratio_limit;$('#rss-action').value=feed.ratio_action;$('#rss-enabled').checked=feed.enabled;
  $('#rss-start').value=feed.download_from?'custom':'all';
  if(feed.download_from)$('#rss-start-date').value=rssLocalDate(feed.download_from);
  updateRssStart();$('#rss-form-title').textContent='Rediger RSS-feed';$('#rss-delete-notice').hidden=feed.ratio_action!=='delete';
 }
 updateRssPath();$('#rss-dialog').showModal();$('#rss-name').focus();
}
function rssFeedCard(feed){
 const card=node('article','tracker-card'),head=node('div','tracker-card-heading');
 head.append(node('h3','',feed.name),node('span','badge'+(feed.status==='active'?' ready':''),{active:'Aktivt',paused:'På pause',pending:'Afventer VPN / synkronisering',error:'Feedfejl'}[feed.status]));
 card.append(head,node('p','muted small',feed.host+' · '+feed.articles+' feedposter'),node('p','torrent-policy','Mappe: '+rssRoot+(feed.folder?'/'+feed.folder:'')+' · Stop-ratio: '+feed.ratio_limit+' eller 49 timers seeding'+' · '+(feed.ratio_action==='delete'?'Slet filer automatisk':'Behold filer')));
 card.append(node('p','torrent-policy',feed.download_from?'Hent fra: '+new Date(feed.download_from).toLocaleString('da-DK'):'Hent alle poster i feedet'));
 if(feed.enabled&&feed.download_from&&feed.download_status)card.append(node('p','muted small',feed.download_status));
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
$('#rss-action').onchange=()=>$('#rss-delete-notice').hidden=$('#rss-action').value!=='delete';
$('#rss-cancel').onclick=()=>$('#rss-dialog').close();
$('#rss-form').onsubmit=async e=>{
 e.preventDefault();if(rssBusy)return;rssBusy=true;$('#rss-save').disabled=true;$('#rss-error').hidden=true;
 try{
  const start=$('#rss-start').value==='all'?null:new Date($('#rss-start-date').value).toISOString();
  await api('/api/rss',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
   id:$('#rss-id').value,name:$('#rss-name').value,url:$('#rss-url').value,folder:$('#rss-folder').value,
   ratio_limit:$('#rss-ratio').value,ratio_action:$('#rss-action').value,
   download_from:start,enabled:$('#rss-enabled').checked})});
  $('#rss-dialog').close();resetRssForm();await refreshRss();toast('Feedet er gemt. Synkroniseres når VPN og seedbox er klar.');
 }catch(e){error('#rss-error',e);}finally{rssBusy=false;$('#rss-save').disabled=false;}
};
refreshRss();setInterval(refreshRss,10000);
