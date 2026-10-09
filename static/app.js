const $ = s => document.querySelector(s);
const csrf = $('meta[name="csrf-token"]').content;
let current, busy = false, deleting, toastTimer;
function node(tag, cls, text) {const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;}
function toast(text){$('#toast').textContent=text;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,4000);}
function error(selector,e){$(selector).textContent=e.message;$(selector).hidden=false;}
async function api(url, options={}){const r=await fetch(url,{...options,headers:{'X-CSRF-Token':csrf,...options.headers}});if(r.status===401){location.href='/login';throw Error('Log ind igen.');}const d=await r.json();if(!r.ok)throw Error(d.error||'Handlingen kunne ikke udføres.');return d;}
function size(n){n=Number(n)||0;for(const unit of ['B','KB','MB','GB','TB']){if(n<1024||unit==='TB')return n.toFixed(n<10?1:0)+' '+unit;n/=1024;}}
function benefitView(data){
 const wrap=node('div','torrent-benefits');
 if(!data||data.status!=='matched'){wrap.append(node('span','muted small',data?.message||'Trackerfordele ukendte'));return wrap;}
 for(const match of data.matches||[]){
  const group=node('div','benefit-group');group.append(node('span','benefit-tracker',match.tracker_name));
  if(match.freeleech>0)group.append(node('span','benefit-badge',match.freeleech+' % Freeleech'));
  if(match.double_upload===true)group.append(node('span','benefit-badge double','Dobbelt upload'));
  if(match.featured)group.append(node('span','benefit-badge','Featured'));
  if(match.internal)group.append(node('span','benefit-badge subtle','Internal'));
  if(match.refundable)group.append(node('span','benefit-badge subtle','Refundable'));
  if(match.freeleech===0&&match.double_upload===false&&!match.featured)group.append(node('span','muted small','Ingen freeleech eller dobbelt upload'));
  if(match.freeleech===null||match.double_upload===null)group.append(node('span','muted small','Nogle fordele er ukendte'));
  wrap.append(group);
 }
 return wrap;
}
function renderRatioPreview(data){
 const target=$('#preview-ratio');target.replaceChildren();
 if(data.status==='pending'){target.append(node('p','muted small','Beregner forventet tracker-ratio...'));return;}
 const estimates=data.ratio_estimates||[];
 if(!estimates.length){target.append(node('p','muted small','Forventet ratio er ukendt. Vælg en tracker med kontotal, og brug en torrentfil eller et magnetlink, der kan slås op.'));return;}
 const number=n=>n===null?'Ukendt':Number(n).toLocaleString('da-DK',{maximumFractionDigits:6});
 for(const estimate of estimates){
  const section=node('div','ratio-estimate'+(estimate.warning?' ratio-warning':''));
  section.append(node('strong','',estimate.tracker_name));
  if(estimate.status!=='ok'){section.append(node('p','muted small',estimate.message));target.append(section);continue;}
  section.append(node('p','ratio-value','Forventet tracker-ratio: '+(estimate.infinite?'∞':number(estimate.projected_ratio))),
   node('p','muted small','Nuværende: '+number(estimate.current_ratio)+' · Torrent: '+size(estimate.torrent_size)+' · Tæller som download: '+size(estimate.charged_download)));
  if(estimate.assumed_no_freeleech)section.append(node('p','muted small','Freeleech er ukendt. Beregningen tæller derfor hele downloadet.'));
  if(estimate.warning){const warning=node('p','ratio-warning-text','Advarsel: din tracker-ratio bliver 0,5 eller lavere efter denne download.');warning.setAttribute('role','alert');section.append(warning);}
  section.append(node('p','muted small','Baseret på kontotal fra '+new Date(estimate.updated_at*1000).toLocaleTimeString('da-DK',{hour:'2-digit',minute:'2-digit'})+'. Hele torrenten downloades; ny upload og andre igangværende downloads er ikke medregnet. Dobbelt upload giver først kredit, når du uploader.'));
  target.append(section);
 }
}
function torrentStatus(t) {
 const states = {
  uploading:'Seeder \u2013 uploader', stalledUP:'Seeder \u2013 venter p\u00e5 downloadere',
  forcedUP:'Seeder \u2013 tvunget start', queuedUP:'Afventer seeding',
  pausedUP:'Seeding sat p\u00e5 pause', stoppedUP:'Seeding stoppet', checkingUP:'Kontrollerer filer f\u00f8r seeding',
  downloading:'Downloader', stalledDL:'Download \u2013 venter p\u00e5 peers', forcedDL:'Downloader \u2013 tvunget start',
  queuedDL:'Download i k\u00f8', pausedDL:'Download sat p\u00e5 pause', stoppedDL:'Download stoppet',
  checkingDL:'Kontrollerer download', metaDL:'Henter torrentoplysninger', forcedMetaDL:'Henter torrentoplysninger',
  checkingResumeData:'Kontrollerer gemt fremdrift', moving:'Flytter filer', missingFiles:'Filer mangler', error:'Fejl'
 };
 return states[t.state] || 'Ukendt status';
}
function seedingProgress(t) {
 const ratio = Math.max(0, Number(t.ratio) || 0);
 const target = Number(t.ratio_limit) > 0 ? Number(t.ratio_limit) : 1;
 const seconds = Math.max(0, Number(t.seeding_time) || 0);
 const minutes = Number(t.seeding_time_limit) > 0 ? Number(t.seeding_time_limit) : 0;
 const fraction = Math.min(1, Math.max(ratio / target, minutes ? seconds / (minutes * 60) : 0));
 return {ratio, target, seconds, minutes, fraction, active:['uploading','stalledUP','forcedUP'].includes(t.state)};
}
function torrentProgress(t) {
 const fraction = Math.max(0, Math.min(1, Number(t.progress) || 0));
 const complete = fraction >= 1;
 const seed = seedingProgress(t);
 const wrap = node('div','torrent-progress'+(complete?' is-seeding':'')+(seed.active&&complete?' seed-active':''));
 const caption = node('div','progress-caption');
 const downloaded = size(t.completed??Math.round((Number(t.size)||0)*fraction))+' af '+size(t.size);
 const text = complete ? 'Seeding: '+Math.floor(seed.fraction*100)+' %' : (fraction*100).toFixed(1)+' %';
 caption.append(node('strong','',text),node('span','muted small',downloaded+' \u00b7 '+(complete?'Download f\u00e6rdig':eta(t.eta))));
 if (complete) {
  const status = node('div','seed-caption');
  status.append(node('strong','seed-state',torrentStatus(t)),node('span','seed-values',
   'Ratio '+seed.ratio.toLocaleString('da-DK',{maximumFractionDigits:2})+' / '+seed.target.toLocaleString('da-DK')+
   ' \u00b7 '+(seed.seconds/3600).toLocaleString('da-DK',{maximumFractionDigits:1})+
   (seed.minutes?' / '+(seed.minutes/60).toLocaleString('da-DK'):'')+' timers seeding'));
  wrap.append(status);
  if(seed.fraction>=1)wrap.append(node('p','seed-complete','Seedingm\u00e5l opfyldt'));
 }
 wrap.append(caption);
 const track=node('div','torrent-progress-track');
 const download=node('progress','progress download-progress');download.max=1;download.value=fraction;
 download.setAttribute('aria-label','Download af '+t.name);
 if(complete)download.setAttribute('aria-hidden','true');
 track.append(download);
 if(complete){
  const overlay=node('progress','progress seed-progress');overlay.max=1;overlay.value=seed.fraction;
  overlay.setAttribute('aria-label','Seeding af '+t.name);
  overlay.setAttribute('aria-valuetext',Math.floor(seed.fraction*100)+' % af seedingm\u00e5let. Ratio '+seed.ratio+' af '+seed.target+
   (seed.minutes?' eller '+seed.minutes/60+' timer.':''));
  track.append(overlay);
 }
 wrap.append(track);return wrap;
}
function card(t){const row=node('article','torrent'),head=node('div','torrent-head');head.append(node('h3','',t.name));const actions=node('div','torrent-actions');for(const [action,label] of [['start','Start'],['stop','Pause'],['delete','Fjern']]){const b=node('button','secondary',label);b.type='button';b.disabled=!current.ready;b.setAttribute('aria-label',label+' '+t.name);b.onclick=async()=>{if(action==='delete'){deleting=t;$('#delete-name').textContent=t.name;$('#delete-error').hidden=true;$('#delete-dialog').showModal();return;}b.disabled=true;try{await api(`/api/torrents/${t.hash}/${action}`,{method:'POST'});await refresh();}catch(e){toast(e.message);}finally{b.disabled=false;}};actions.append(b);}head.append(actions);row.append(head,node('p','torrent-meta',`${(Number(t.progress)*100).toFixed(1)}% · ${size(t.size)} · ↓ ${size(t.dlspeed)}/s · ↑ ${size(t.upspeed)}/s · Ratio ${Number(t.ratio||0).toFixed(2)} · ${torrentStatus(t)}`));if(Number(t.ratio_limit)>=0&&t.ratio_limit!==undefined&&t.ratio_limit!==null){row.append(node('p','torrent-policy','Stop-ratio: '+t.ratio_limit+' \u00b7 '+(t.share_limit_action==='RemoveWithContent'?'Slet filer automatisk':'Behold filer')));}row.append(benefitView(t.benefits));row.append(torrentProgress(t));if(t.rss_feed)row.append(node('p','torrent-policy','RSS: '+t.rss_feed));return row;}
function eta(seconds){if(!Number.isFinite(Number(seconds))||Number(seconds)<0||Number(seconds)>=8640000)return 'Ukendt tid tilbage';seconds=Math.round(seconds);if(seconds<60)return seconds+' sek. tilbage';if(seconds<3600)return Math.ceil(seconds/60)+' min. tilbage';return Math.floor(seconds/3600)+' t. '+Math.ceil((seconds%3600)/60)+' min. tilbage';}
function renderDownloadLists(data){
 const manual=data.torrents.filter(t=>!t.rss_feed),rss=data.torrents.filter(t=>t.rss_feed);
 $('#torrent-list').replaceChildren(...manual.map(card));$('#empty').hidden=manual.length>0;
 $('#rss-torrent-list').replaceChildren(...rss.map(card));$('#rss-empty').hidden=rss.length>0;$('#rss-count').textContent=rss.length;
 for(const [items,prefix] of [[manual,''],[rss,'rss-']])for(const [field,id] of [['dlspeed','dl'],['upspeed','ul']])$('#'+prefix+id).textContent=size(items.reduce((sum,t)=>sum+(Number(t[field])||0),0))+'/s';
}
function renderFlow(data){
 const state=data.ready?'active':'blocked',flow=$('#traffic-flow');
 flow.dataset.state=state;
 $('#flow-status').textContent=data.ready?'VPN aktiv':data.enabled?'Forbindelse blokeret':'Seedbox stoppet';
 const code=data.ready?countryCode(data.country):null;
 $('#flow-country').textContent=data.ready?(countryName(data.country)||'Ukendt land'):'Afventer forbindelse';
 const icon=$('#flow-vpn-icon'),key=code||'unknown';
 if(icon.dataset.country!==key){icon.dataset.country=key;const content=code?node('img'):node('span','','VPN');if(code){content.src='/static/flags/'+code.toLowerCase()+'.svg';content.alt='';content.width=32;content.height=24;}icon.replaceChildren(content);}
}
function render(data){current=data;renderFlow(data);$('#vpn-message').textContent=data.message;$('#vpn-badge').textContent=data.ready?'VPN aktiv':'Blokeret';$('#vpn-badge').className='badge'+(data.ready?' ready':'');$('#new-torrent').disabled=!data.ready;$('#stop').hidden=!data.enabled;$('#connect').textContent=data.enabled?'Gem VPN-valg':'Start seedbox';$('#dl').textContent=size(data.transfer?.dl_info_speed)+'/s';$('#ul').textContent=size(data.transfer?.up_info_speed)+'/s';$('#count').textContent=data.torrents.filter(t=>!t.rss_feed).length;$('#download-path').textContent='Downloadmappe: '+data.download_path;$('#qbit-version').textContent=data.version?'qBittorrent '+data.version:'qBittorrent inkluderet';$('#public-address').replaceChildren(...(data.public_ip?[document.createTextNode(`${data.public_ip}:${data.port} · `),countryInfo(data.country),document.createTextNode(' · Netkort: tun0')]:[]));
 const select=$('#profile'),chosen=select.value||data.profile_id;const options=[node('option','','Vælg VPN')];options[0].value='';for(const p of data.profiles){const o=node('option','',p.name+(p.relay_enabled?' · bruges til TCP':p.desired?' · startet':' · slukket'));o.value=p.id;o.disabled=p.relay_enabled;options.push(o);}if(data.profile_id&&!data.profiles.some(p=>p.id===data.profile_id)){const o=node('option','','Valgt VPN er ikke tilgængelig');o.value=data.profile_id;options.push(o);}select.replaceChildren(...options);select.value=chosen;renderDownloadLists(data);$('#updated').textContent='Opdateret '+new Date().toLocaleTimeString('da-DK',{hour:'2-digit',minute:'2-digit'});}
async function refresh(){if(busy)return;try{render(await api('/api/status'));$('#error').hidden=true;}catch(e){error('#error',e);$('#new-torrent').disabled=true;renderFlow({ready:false,enabled:true});$('#flow-status').textContent='Status utilgængelig';}}
async function settings(enabled){busy=true;$('#connect').disabled=true;$('#stop').disabled=true;try{await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile_id:$('#profile').value,enabled})});toast(enabled?'VPN-valget er gemt. Starter når VPN er klar.':'Seedbox stoppes.');}catch(e){toast(e.message);}finally{busy=false;$('#connect').disabled=false;$('#stop').disabled=false;}await refresh();}
$('#settings-form').onsubmit=e=>{e.preventDefault();settings(true);};$('#stop').onclick=()=>settings(false);
let addMethod='magnet';
function chooseMethod(method){addMethod=method;$('#magnet-fields').hidden=method!=='magnet';$('#file-fields').hidden=method!=='file';$('#method-magnet').setAttribute('aria-pressed',method==='magnet');$('#method-file').setAttribute('aria-pressed',method==='file');$('#add-error').hidden=true;}
$('#method-magnet').onclick=()=>chooseMethod('magnet');$('#method-file').onclick=()=>chooseMethod('file');
$('#new-torrent').onclick=()=>{$('#add-form').reset();chooseMethod('magnet');$('#add-error').hidden=true;$('#add-dialog').showModal();$('#magnet').focus();};
document.querySelectorAll('.close').forEach(b=>b.onclick=()=>b.closest('dialog').close());
let pendingTorrent;
$('#add-form').onsubmit=e=>{e.preventDefault();$('#add-error').hidden=true;try{const body=new FormData();const magnet=$('#magnet').value.trim();const file=$('#torrent-file').files[0];if(addMethod==='magnet'){if(!magnet.startsWith('magnet:?'))throw Error('Indtast et gyldigt magnetlink.');body.set('magnet',magnet);}else{if(!file||!file.name.toLowerCase().endsWith('.torrent'))throw Error('Vælg en .torrent-fil.');body.set('torrent',file);}pendingTorrent=body;$('#ratio-form').reset();$('#ratio-source').textContent=addMethod==='file'?file.name:'Torrent fra magnetlink';$('#ratio-error').hidden=true;$('#ratio-delete-notice').hidden=true;$('#add-dialog').close();$('#ratio-dialog').showModal();prepareBenefits();$('#ratio-limit').focus();}catch(e){error('#add-error',e);}};
let previewTimer,previewGeneration=0;
function prepareBenefits(){
 const select=$('#benefit-tracker');select.replaceChildren(node('option','','Find automatisk blandt mine trackere'));select.firstChild.value='';
 for(const tracker of typeof trackerData==='undefined'?[]:trackerData){const option=node('option','',tracker.name);option.value=tracker.id;select.append(option);}
 loadPreviewBenefits();
}
async function loadPreviewBenefits(){
 clearTimeout(previewTimer);const generation=++previewGeneration;
 $('#preview-benefits').replaceChildren(benefitView({status:'pending',message:'Slår trackerfordele op...'}));
 renderRatioPreview({status:'pending'});
 async function check(){
  if(!pendingTorrent||!$('#ratio-dialog').open||generation!==previewGeneration)return;
  try{const body=new FormData();for(const [key,value] of pendingTorrent)if(key==='magnet'||key==='torrent')body.append(key,value);body.set('tracker_id',$('#benefit-tracker').value);
   const result=await api('/api/torrents/preview',{method:'POST',body});
   if(generation!==previewGeneration||!$('#ratio-dialog').open)return;
   $('#preview-benefits').replaceChildren(benefitView(result));
   renderRatioPreview(result);
   if(result.status==='pending'||result.ratio_estimates?.some(e=>e.status==='pending'))previewTimer=setTimeout(check,2000);
  }catch(e){if(generation===previewGeneration){$('#preview-benefits').replaceChildren(benefitView({status:'unknown',message:'Trackerfordele ukendte — '+e.message}));renderRatioPreview({status:'unknown'});}}
 }
 await check();
}
$('#benefit-tracker').onchange=loadPreviewBenefits;
$('#ratio-dialog').addEventListener('close',()=>{clearTimeout(previewTimer);previewGeneration++;});
$('#ratio-action').onchange=()=>$('#ratio-delete-notice').hidden=$('#ratio-action').value!=='delete';
$('#ratio-dialog').addEventListener('cancel',e=>{if($('#ratio-save').disabled)e.preventDefault();});
$('#ratio-back').onclick=()=>{$('#ratio-dialog').close();$('#add-dialog').showModal();};
$('#ratio-form').onsubmit=async e=>{e.preventDefault();if(!pendingTorrent)return;$('#ratio-save').disabled=true;$('#ratio-back').disabled=true;$('#ratio-dialog .close').disabled=true;$('#ratio-error').hidden=true;try{pendingTorrent.set('ratio_limit',$('#ratio-limit').value);pendingTorrent.set('ratio_action',$('#ratio-action').value);await api('/api/torrents',{method:'POST',body:pendingTorrent});pendingTorrent=null;$('#ratio-dialog').close();toast('Torrent tilføjet');await refresh();}catch(e){error('#ratio-error',e);}finally{$('#ratio-save').disabled=false;$('#ratio-back').disabled=false;$('#ratio-dialog .close').disabled=false;}};
$('#delete-form').onsubmit=async e=>{e.preventDefault();$('#delete-save').disabled=true;try{await api(`/api/torrents/${deleting.hash}/delete`,{method:'POST'});$('#delete-dialog').close();await refresh();}catch(e){error('#delete-error',e);}finally{$('#delete-save').disabled=false;}};
function showView(focus=false){
 const view=location.hash==='#connection'?'connection':location.hash==='#trackers'?'trackers':location.hash==='#rss'?'rss':'torrents';
 const vpn=view==='connection',trackers=view==='trackers',rss=view==='rss';
 $('#connection').hidden=!vpn;$('#downloads-view').hidden=vpn||trackers||rss;$('#trackers-view').hidden=!trackers;$('#new-torrent').hidden=vpn||trackers||rss;$('#traffic-flow').hidden=trackers;$('#rss-view').hidden=!rss;
 $('#breadcrumb').textContent='Seedbox / '+(vpn?'VPN-forbindelse':trackers?'Trackere':rss?'RSS-feeds':'Downloads');
 $('#page-title').textContent=vpn?'Din VPN-forbindelse':trackers?'Dine trackere':rss?'Dine RSS-feeds':'Manuelle downloads';
 $('#page-description').textContent=vpn?'Vælg VPN-profil, og se seedboxens forbindelse og beskyttelse.':trackers?'Forbind dine trackerkonti, og saml statistikken i FjordSeed.':rss?'Automatiske downloads med dine egne regler for mapper og seeding.':'qBittorrent samlet ét sted, med trafik gennem din VPN.';
 document.querySelectorAll('.nav').forEach(link=>{const active=link.hash==='#'+view;link.classList.toggle('active',active);if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
 if(focus)$('#page-title').focus({preventScroll:true});
}
window.addEventListener('hashchange',()=>showView(true));
showView();refresh();setInterval(refresh,4000);
