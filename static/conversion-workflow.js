(() => {
 const $=id=>document.getElementById(id), labels={full:'Fuld konvertering',video:'Kun video',audio:'Kun lyd'};
 const size=n=>Number.isFinite(n)?new Intl.NumberFormat('da-DK',{maximumFractionDigits:1}).format(n/1024**3)+' GiB':'Ukendt';
 const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
 const button=(text,fn,cls='secondary')=>{const b=node('button',text,cls);b.type='button';b.onclick=fn;return b;};
 const post=(action,data)=>api('/api/conversion/workflow/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 let mode=null, items=[], jobs=[], selected=new Set(), cache=new Map(), failed=new Set(), loading=false, limit=40, review=[], step=0, busy=false, activeProbe=false;
 const error=(id,message)=>{$(id).textContent=message||'';$(id).hidden=!message;};
 const streams=(file,kind)=>(cache.get(file.id)?.media||file.media)?.streams?.filter(s=>s.codec_type===kind)||[];
 const streamLabel=s=>[s.tags?.language||'Ukendt sprog',s.codec_name?.toUpperCase(),s.channel_layout||(s.channels?s.channels+' kanaler':''),s.tags?.title].filter(Boolean).join(' · ');
 function defaults(file){return {mode,bitrate:30,dolby_vision_mode:mode==='audio'?'preserve':'separate',audio_codec:mode==='video'||streams(file,'audio').some(s=>s.channels>6)?'copy':'eac3',audio:streams(file,'audio').map(s=>s.index),subtitle:streams(file,'subtitle').map(s=>s.index)};}
 function estimate(file,options){
  const media=cache.get(file.id)?.media||file.media,duration=Number(media?.format?.duration);if(!duration)return null;
  const audio=media.streams.filter(s=>s.codec_type==='audio'),bps=s=>Number(s.bit_rate||s.tags?.BPS||s.tags?.['BPS-eng']);
  if(audio.some(s=>!bps(s)))return null;
  let rate=audio.filter(s=>options.audio.includes(s.index)).reduce((sum,s)=>sum+bps(s)+(options.audio_codec!=='copy'&&s.codec_name!==options.audio_codec?(s.channels>2?640000:192000):0),0);
  return options.mode==='audio'?Math.max(0,file.size-audio.reduce((sum,s)=>sum+bps(s),0)*duration/8+rate*duration/8):(options.bitrate*1e6+rate)*duration/8*1.01;
 }
 function visible(){const q=$('cw-search').value.toLocaleLowerCase();return items.filter(f=>!f.converted&&(!f.skipped_modes?.includes(mode)||$('cw-show-skipped').checked)&&(!q||(f.title+' '+f.name).toLocaleLowerCase().includes(q)));}
 function selection(){ $('cw-count').textContent=selected.size?selected.size+' film valgt':'Ingen film valgt';$('cw-configure').disabled=!selected.size; }
 async function media(file){
  if(cache.has(file.id))return cache.get(file.id);
  const data=await api('/api/conversion/workflow/'+file.id+'/media');cache.set(file.id,data);failed.delete(file.id);return data;
 }
 async function probeVisible(){
  if(activeProbe||!mode)return;activeProbe=true;
  try{for(const file of visible().slice(0,limit)){
   if(!mode||location.hash!=='#conversion')break;
   if(cache.has(file.id)||failed.has(file.id))continue;
   try{await media(file);}catch(e){failed.add(file.id);}
   if(!$('cw-dialog').open)renderFilms();
  }}finally{activeProbe=false;}
 }
 function renderFilms(){
  const list=$('cw-films');list.replaceChildren();
  const found=visible();$('cw-status').textContent=found.length+' film · '+labels[mode];
  if(!found.length)list.append(node('p','Ingen film matcher dette valg. Prøv søgningen eller vis oversprungne film.','muted'));
  for(const file of found.slice(0,limit)){
   const row=node('article',null,'cw-film'),check=node('input');check.type='checkbox';check.checked=selected.has(file.id);check.disabled=!file.eligible||file.skipped_modes?.includes(mode);check.setAttribute('aria-label','Vælg '+file.title);check.onchange=()=>{check.checked?selected.add(file.id):selected.delete(file.id);selection();};
   const cover=file.cover?node('img'):node('span','▣');cover.className='cw-cover';if(file.cover){cover.src=file.cover;cover.alt='';cover.loading='lazy';}
   const info=node('div');info.append(node('h3',file.title),node('p',size(file.size)+' · '+file.name,'muted small'));
   const data=cache.get(file.id)?.media||file.media;
   if(data){
    if(mode!=='audio'){const v=streams(file,'video')[0]||{},dv=v.side_data_list?.find(s=>s.side_data_type==='DOVI configuration record');info.append(node('p',[v.codec_name?.toUpperCase(),v.width&&v.width+' × '+v.height,dv?'Dolby Vision '+dv.dv_profile+(dv.dv_profile===8?'.'+dv.dv_bl_signal_compatibility_id:''):'Ingen Dolby Vision'].filter(Boolean).join(' · '),'small'));}
    if(mode!=='video')info.append(node('p',streams(file,'audio').map(streamLabel).join(' / ')||'Ingen lydspor','small'));
    const estimates=node('div',null,'cw-estimates'),opts=defaults(file);
    for(const rate of mode==='audio'?[null]:[20,30,40]){if(rate)opts.bitrate=rate;const bytes=estimate(file,opts);estimates.append(node('span',(rate?rate+' Mbps':'Lydvalg')+' · '+size(file.size)+' → '+(bytes===null?'Estimat utilgængeligt':size(bytes))));}
    info.append(estimates);
   }else info.append(node('p',failed.has(file.id)?'Medieoplysninger kunne ikke læses.':'Læser formater og størrelsesestimater …','muted small'));
   if(failed.has(file.id))info.append(button('Prøv medieoplysninger igen',()=>{failed.delete(file.id);probeVisible();},'quiet'));
   if(!file.eligible)info.append(node('p',file.reason,'muted small'));
   const skipped=file.skipped_modes?.includes(mode),skip=button(skipped?'Gendan':'Spring over',async()=>{
    skip.disabled=true;try{await post('skip',{id:file.id,mode,skip:!skipped});file.skipped_modes=(file.skipped_modes||[]).filter(m=>m!==mode);if(!skipped)file.skipped_modes.push(mode);selected.delete(file.id);renderFilms();}catch(e){error('cw-error',e.message);skip.disabled=false;}
   },'quiet');row.append(check,cover,info,skip);list.append(row);
  }
  if(found.length>limit)list.append(button('Vis flere film',()=>{limit+=40;renderFilms();probeVisible();}));selection();
 }
 function renderJobs(){
  const list=$('cw-jobs');list.replaceChildren();const active=jobs.filter(j=>!['done','cancelled'].includes(j.state)),show=[...active.slice(0,100),...jobs.filter(j=>j.state==='done').slice(-10)];
  if(active.length>100)list.append(node('p','Viser de første 100 af '+active.length+' film i kø.','muted small'));
  if(!show.length)list.append(node('p','Ingen film i kø.','muted'));
  show.forEach((j,index)=>{const row=node('div',null,'cw-job'),copy=node('div');copy.append(node('strong',j.name),node('p',(labels[j.options.mode]||'')+' · '+({queued:'Venter',starting:'Klargør',running:'Arbejder',done:'Færdig',error:'Kræver kontrol'}[j.state]||j.state),'small'),node('p',j.detail||'','muted small'));
   if(j.state==='running'){const progress=node('progress');progress.max=100;if(j.phase==='encoding')progress.value=j.progress||0;copy.append(progress);}
   row.append(copy);
   if(j.state==='queued'||(j.state==='error'&&!j.library_id))row.append(button('Fjern fra kø',()=>act('cancel',j.id),'quiet'));
   if(j.state==='error')row.append(button('Prøv igen',()=>act('retry',j.id)));
   list.append(row);
  });
 }
 async function act(action,id){try{await post(action,{id});await load();}catch(e){error('cw-error',e.message);}}
 async function load(){
  if(loading)return;loading=true;error('cw-error','');
  try{const data=await api('/api/conversion/workflow');items=data.items||[];jobs=data.jobs||[];for(const id of selected)if(!items.some(i=>i.id===id&&i.eligible))selected.delete(id);if(mode){renderFilms();probeVisible();}renderJobs();}
  catch(e){error('cw-error',e.message);$('cw-jobs').textContent='Køen kunne ikke indlæses: '+e.message;}
  finally{loading=false;}
 }
 function fieldset(title){const f=node('fieldset');f.append(node('legend',title));return f;}
 function select(label,values,value,change){const l=node('label',label),s=node('select');for(const [id,text] of values){const o=node('option',text);o.value=id;s.append(o);}s.value=value;s.onchange=()=>change(s.value);l.append(s);return l;}
 function trackChoices(file,kind,options,container,update){for(const s of streams(file,kind)){const l=node('label',null,'check-label'),c=node('input');c.type='checkbox';c.checked=options[kind].includes(s.index);c.onchange=()=>{options[kind]=streams(file,kind).filter(t=>t.index===s.index?c.checked:options[kind].includes(t.index)).map(t=>t.index);update();};l.append(c,node('span',streamLabel(s)));container.append(l);}}
 const actions=[['keep','Behold original · seed indtil du stopper'],['stop_keep','Behold original · stop efter konvertering'],['delete','Slet original ved målratio eller 50 timers seedtid'],['automatic','Optimér upload · slet original bagefter'],['delete_ratio','Slet original kun ved målratio'],['delete_time','Seed i X minutter · slet original bagefter']];
 function showStep(){
  error('cw-dialog-error','');const fields=$('cw-fields');fields.replaceChildren();$('cw-prev').disabled=step===0;$('cw-skip-film').hidden=step===review.length;
  if(step===review.length){
   $('cw-step').textContent='KLAR TIL START';$('cw-dialog-title').textContent='Gennemse din konverteringskø';$('cw-next').textContent='Start kø · '+review.length+' film';$('cw-next').disabled=!review.length;
   review.forEach((r,i)=>{const div=node('div',null,'cw-review-item');div.append(node('strong',r.file.title),node('p',labels[mode]+(mode==='audio'?'':' · '+r.options.bitrate+' Mbps')+(mode==='video'?'':' · '+r.options.audio_codec.toUpperCase())),node('p',size(r.file.size)+' → '+size(estimate(r.file,r.options))),node('p',actions.find(a=>a[0]===r.policy.ratio_action)[1],'muted small'),button('Ret indstillinger',()=>{step=i;showStep();},'quiet'));fields.append(div);});
   fields.append(node('p','Filmene behandles én ad gangen på serveren. Efter kontrol flyttes originalen gennem qBittorrent til Seeder. Seedtid tæller ikke under flytningen. Allerede optjent ratio og aktiv seedtid bevares.','muted small'));return;
  }
  const current=review[step],file=current.file,o=current.options,p=current.policy;
  $('cw-step').textContent=labels[mode]+' · FILM '+(step+1)+' AF '+review.length;$('cw-dialog-title').textContent=file.title;$('cw-next').textContent=step===review.length-1?'Gennemse kø →':'Næste film →';$('cw-next').disabled=false;
  const live=node('div',null,'cw-live');live.setAttribute('aria-live','polite');
  function update(){const bytes=estimate(file,o);live.replaceChildren(node('strong',size(file.size)+' → '+(bytes===null?'Estimat utilgængeligt':size(bytes))),node('small',bytes===null?'Filens varighed eller lydbitrate mangler.':(bytes>file.size?'Forventet større fil · ':'Forventet besparelse · ')+size(Math.abs(file.size-bytes))),node('small','Originalen bevares i Seeder. Estimatet er ikke en garanti og omfatter ikke originalens ekstra plads.'));}
  if(mode!=='audio'){
   const video=fieldset('Video'),grid=node('div',null,'cw-field-grid');grid.append(select('Videobitrate',[[20,'20 Mbps'],[30,'30 Mbps'],[40,'40 Mbps']],o.bitrate,v=>{o.bitrate=Number(v);update();}),select('Dolby Vision', [['separate','Fjern fra filmen · gem separat (HDR10)'],['preserve','Behold · profil 8.1']],o.dolby_vision_mode,v=>{o.dolby_vision_mode=v;update();}));video.append(grid,node('p','Profil 7 og 8.1 kan behandles. Profil 7 bliver 8.1; det ekstra billedlag følger kun med originalen. Filer uden Dolby Vision påvirkes ikke.','muted small'));fields.append(video);
  }
  if(mode!=='video'){
   const audio=fieldset('Lydsprog og spor');trackChoices(file,'audio',o,audio,update);
   const toggle=node('label',null,'check-label'),check=node('input');check.type='checkbox';check.checked=o.audio_codec!=='copy';const codec=select('Kompatibelt lydformat',[['eac3','E-AC3 (Dolby Digital Plus)'],['ac3','AC3 (Dolby Digital)']],o.audio_codec==='copy'?'eac3':o.audio_codec,v=>{o.audio_codec=v;update();});codec.hidden=!check.checked;check.onchange=()=>{o.audio_codec=check.checked?codec.querySelector('select').value:'copy';codec.hidden=!check.checked;update();};toggle.append(check,node('span','Tilføj kompatibel lyd · behold de valgte originalspor'));audio.append(toggle,codec,node('p','Kanalantal bevares, herunder 5.1. Spor over 5.1 kan beholdes som original lyd, men får ikke en AC3/E-AC3-kopi i denne version.','muted small'));fields.append(audio);
  }
  if(mode==='full'){const subs=fieldset('Undertekster');trackChoices(file,'subtitle',o,subs,update);if(!streams(file,'subtitle').length)subs.append(node('p','Ingen indbyggede undertekster.','muted'));fields.append(subs);}
  const original=fieldset('Originalen efter konvertering'),extra=node('div');
  function policyFields(){extra.replaceChildren();if(!['keep','stop_keep'].includes(p.ratio_action)){
   const timed=p.ratio_action==='delete_time',label=node('label',timed?'Aktiv seedtid i minutter':'Målratio'),input=node('input');input.type='number';input.min=1;input.max=timed?525600:10000;input.step=timed?'1':'any';input.required=true;input.value=timed?p.seed_minutes:p.ratio_limit;input.oninput=()=>{p[timed?'seed_minutes':'ratio_limit']=Number(input.value);};label.append(input);extra.append(label,node('p',timed?'Når målet er nået, slettes original og torrent, også ved aktive downloadere. Optjent aktiv seedtid tæller med.':'Målene bruger reel upload og aktiv seedtid. Pauser og flytning tæller ikke. Oprydning venter på aktive downloadere.','muted small'));}}
  original.append(select('Seeding og oprydning',actions,p.ratio_action,v=>{p.ratio_action=v;policyFields();}),extra,node('p','Kun originalen i Seeder er omfattet af oprydning. Den konverterede film bliver i biblioteket. Flere film i samme torrent skal have samme seedingvalg, fordi qBittorrent håndterer hele torrenten.','muted small'));policyFields();fields.append(original);fields.prepend(live);update();
 }
 function validCurrent(){if(step>=review.length)return true;const r=review[step],o=r.options;if(mode!=='video'&&streams(r.file,'audio').length&&!o.audio.length){error('cw-dialog-error','Vælg mindst ét lydspor.');return false;}if(o.audio_codec!=='copy'&&streams(r.file,'audio').some(s=>o.audio.includes(s.index)&&s.codec_name!==o.audio_codec&&(!s.channels||s.channels>6))){error('cw-dialog-error','Et valgt spor har mere end 5.1 eller ukendt kanalantal. Behold original lyd, eller fravælg sporet.');return false;}return true;}
 $('cw-configure').onclick=async()=>{
  if(busy)return;busy=true;$('cw-configure').disabled=true;error('cw-error','');
  try{review=[];for(const file of items.filter(f=>selected.has(f.id))){const data=await media(file);review.push({file,fingerprint:data.fingerprint,options:defaults(file),policy:{ratio_action:'keep',ratio_limit:1,seed_minutes:60}});}step=0;showStep();$('cw-dialog').showModal();}
  catch(e){error('cw-error',e.message);}finally{busy=false;selection();}
 };
 $('cw-form').onsubmit=async e=>{e.preventDefault();if(busy||!validCurrent())return;if(step<review.length){step++;showStep();return;}busy=true;$('cw-next').disabled=true;
  try{await post('queue',{items:review.map(r=>({id:r.file.id,options:r.options,policy:r.policy,fingerprint:r.fingerprint}))});$('cw-dialog').close();selected.clear();await load();}
  catch(e){error('cw-dialog-error',e.message);}finally{busy=false;$('cw-next').disabled=false;}
 };
 $('cw-prev').onclick=()=>{if(step>0){step--;showStep();}};
 $('cw-skip-film').onclick=()=>{selected.delete(review[step].file.id);review.splice(step,1);showStep();selection();};
 $('cw-close').onclick=()=>{if(!busy)$('cw-dialog').close();};$('cw-dialog').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 document.querySelectorAll('#cw-cards [data-mode]').forEach(card=>card.onclick=()=>{mode=card.dataset.mode;selected.clear();limit=40;$('cw-cards').hidden=true;$('cw-library').hidden=false;$('cw-title').textContent=labels[mode];renderFilms();load();});
 $('cw-back').onclick=()=>{mode=null;selected.clear();$('cw-cards').hidden=false;$('cw-library').hidden=true;};
 $('cw-search').oninput=()=>{limit=40;renderFilms();probeVisible();};$('cw-show-skipped').onchange=()=>{renderFilms();probeVisible();};
 $('cw-refresh').onclick=()=>{failed.clear();cache.clear();load();};$('cw-queue-refresh').onclick=load;
 window.addEventListener('hashchange',()=>{if(location.hash==='#conversion')load();});
 setInterval(()=>{if(location.hash==='#conversion'&&!document.hidden&&!$('cw-dialog').open)load();},15000);
 if(location.hash==='#conversion')load();
})();
