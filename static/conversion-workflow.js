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
 const codecNames={eac3:'E-AC3 (Dolby Digital Plus)',ac3:'AC3 (Dolby Digital)'};
 const targetCodecs=o=>o.audio_codec==='both'?['eac3','ac3']:o.audio_codec==='copy'?[]:[o.audio_codec];
 const missingCodecs=(s,o)=>(o.audio_conversions?o.audio_conversions[s.index]||[]:o.audio.includes(s.index)?targetCodecs(o):[]).filter(c=>s.codec_name!==c);
 const supportedAudio=s=>Number.isInteger(s.channels)&&s.channels>=1&&s.channels<=6&&['mono','stereo','2.1','3.0','3.0(back)','quad','quad(side)','4.0','3.1','4.1','5.0','5.0(side)','5.1','5.1(side)'].includes(s.channel_layout||({1:'mono',2:'stereo'})[s.channels]);
 const audioSummary=o=>o.audio_conversions?o.audio.length+' originalspor · '+Object.values(o.audio_conversions).reduce((n,c)=>n+c.length,0)+' konverterede spor':targetCodecs(o).map(c=>codecNames[c]).join(' + ')||'Kun valgte originalspor';
 function defaults(file){return {mode,bitrate:30,dolby_vision_mode:mode==='audio'?'preserve':'separate',audio_codec:'copy',audio_conversions:{},audio:streams(file,'audio').map(s=>s.index),subtitle:streams(file,'subtitle').map(s=>s.index),delete_original:false};}
 function estimate(file,options){
  const media=cache.get(file.id)?.media||file.media,duration=Number(media?.format?.duration);if(!duration)return null;
  const audio=media.streams.filter(s=>s.codec_type==='audio'),bps=s=>Number(s.bit_rate||s.tags?.BPS||s.tags?.['BPS-eng']);
  if(audio.some(s=>!bps(s)))return null;
  let rate=audio.reduce((sum,s)=>sum+(options.audio.includes(s.index)?bps(s):0)+missingCodecs(s,options).length*(s.channels>2?640000:192000),0);
  return options.mode==='audio'?Math.max(0,file.size-audio.reduce((sum,s)=>sum+bps(s),0)*duration/8+rate*duration/8):(options.bitrate*1e6+rate)*duration/8*1.01;
 }
 function estimateCard(file,options,label){
  const bytes=estimate(file,options),card=node('div',null,'cw-estimate');
  card.append(node('span',label,'cw-estimate-label'),node('span','Forventet slutstørrelse','cw-estimate-caption'),node('strong',bytes===null?'Ukendt':size(bytes),'cw-estimate-size'));
  if(bytes===null){card.append(node('span','Varighed eller lydbitrate mangler','cw-estimate-change'));return card;}
  const difference=file.size-bytes,amount=Math.abs(difference),percent=file.size>0?' · '+new Intl.NumberFormat('da-DK',{maximumFractionDigits:1}).format(amount/file.size*100)+' %':'';
  const saved=amount>0&&amount<1024**3/10?'< 0,1 GiB':size(amount);
  card.classList.add(difference>0?'is-saving':difference<0?'is-growing':'is-unchanged');
  card.append(node('span',difference===0?'Uændret størrelse':(difference>0?'Spar ':'Ekstra plads: ')+saved+percent,'cw-estimate-change'));
  return card;
 }
 // Planning ranges, not measured server performance. Include preparation,
 // remuxing and verification I/O; audio outputs are charged independently.
 function timeEstimate(file,options){
  const media=cache.get(file.id)?.media||file.media,duration=Number(media?.format?.duration);
  const output=estimate(file,options);
  if(!Number.isFinite(duration)||duration<=0||!Number.isFinite(file.size)||file.size<=0||output===null||!Number.isFinite(output))return null;
  const ioBytes=3*file.size+3*output;
  let low=ioBytes/(160*1024**2),high=ioBytes/(40*1024**2);
  const audioWork=streams(file,'audio').reduce((n,s)=>n+missingCodecs(s,options).length*Math.max(1,(s.channels||2)/2),0);
  low+=duration*audioWork/60;high+=duration*audioWork/10;
  if(options.mode!=='audio'){
   const video=streams(file,'video')[0],parts=String(video?.avg_frame_rate||video?.r_frame_rate||'').split('/').map(Number);
   const fps=parts.length===2?parts[0]/parts[1]:parts[0];
   if(!video?.width||!video?.height||!Number.isFinite(fps)||fps<=0)return null;
   const pixels=Math.max(.25,video.width*video.height/(3840*2160));
   low+=duration*fps*pixels/80;high+=duration*fps*pixels/12;
  }
  return {low:low+30,high:high+120};
 }
 function timeRange(value){
  if(!value)return 'Kan ikke beregnes';
  const minutes=seconds=>Math.max(1,Math.ceil(seconds/60));
  const format=n=>n<60?n+' min':Math.floor(n/60)+' t'+(n%60?' '+n%60+' min':'');
  const low=minutes(value.low),high=minutes(value.high);
  return 'Ca. '+format(low)+(low===high?'':' – '+format(high));
 }
 function timeCard(file,options){
  const card=node('div',null,'cw-estimate'),value=timeEstimate(file,options);
  card.append(node('span','Groft tidsestimat','cw-estimate-label'),node('strong',timeRange(value),'cw-estimate-size'),node('span',value?'Inkl. klargøring, konvertering og kontrol. Ikke målt på serveren.':'Filstørrelse, varighed, bitrate eller videooplysninger mangler.','muted small'));
  return card;
 }
 function queueTimeCard(){
  const card=node('div',null,'cw-estimate'),values=review.map(r=>timeEstimate(r.file,r.options)),known=values.filter(Boolean);
  const total=known.reduce((sum,v)=>({low:sum.low+v.low,high:sum.high+v.high}),{low:0,high:0});
  card.append(node('span','Samlet tid · '+review.length+' valgte film','cw-estimate-label'),node('strong',known.length===values.length&&known.length?timeRange(total):'Samlet tid ukendt','cw-estimate-size'));
  if(known.length<values.length&&known.length)card.append(node('span',timeRange(total)+' for '+known.length+' af '+values.length+' film','muted small'));
  card.append(node('p','Groft skøn, ikke målt på serveren. Filmene behandles én ad gangen. Ventetid i en eksisterende kø og efterfølgende seeding er ikke medregnet. Belastning og NAS/netværk kan give længere tid.','muted small'));
  const basis=node('details');basis.append(node('summary','Beregningsgrundlag'),node('p','Antager 40–160 MiB/s samlet læsning/skrivning og flere gennemløb til klargøring og kontrol. Lyd: 10–60 gange afspilningshastigheden pr. stereospor, vægtet efter kanalantal. Video: GPU-konvertering svarende til 12–80 billeder/s i 4K. Det er planlægningsantagelser, ikke målte hastigheder.','muted small'));card.append(basis);
  return card;
 }
 function savings(file){
  if(!(cache.get(file.id)?.media||file.media))return null;
  const options=defaults(file);if(mode!=='audio')options.bitrate=20;
  const bytes=estimate(file,options);return bytes===null?null:Math.round(file.size-bytes);
 }
 function compareSavings(a,b){const x=savings(a),y=savings(b);return x===null&&y!==null?1:y===null&&x!==null?-1:x!==null&&y!==null&&x!==y?y-x:(a.title||a.name).localeCompare(b.title||b.name,'da')||a.id.localeCompare(b.id);}
 function visible(){const q=$('cw-search').value.toLocaleLowerCase();return items.filter(f=>(!f.completed_modes?.includes(mode)||$('cw-show-completed').checked)&&(!f.skipped_modes?.includes(mode)||$('cw-show-skipped').checked)&&(!q||(f.title+' '+f.name).toLocaleLowerCase().includes(q))).sort(compareSavings);}
 let selectionExit=null;
 function selectionVisibility(show){
  const menu=$('cw-selection'),library=$('cw-library');menu.inert=!show;
  if(show){
   if(selectionExit){selectionExit.reverse();selectionExit=null;}
   menu.hidden=false;library.classList.add('has-selection');return;
  }
  if(menu.hidden||selectionExit)return;
  const animation=menu.getAnimations().find(a=>a.effect?.target===menu);
  const hide=()=>{menu.hidden=true;library.classList.remove('has-selection');};
  if(!animation){hide();return;}
  // Reverse from the current position, including when selection changes mid-drop.
  selectionExit=animation;animation.reverse();
  const finish=()=>{if(selectionExit===animation){selectionExit=null;hide();}};
  animation.finished.then(finish,finish);
 }
 function selection(){
  const count=selected.size;selectionVisibility(!!count);
  $('cw-count').textContent=count+' film valgt';for(const id of['cw-configure','cw-skip-selected','cw-clear-selected'])$(id).disabled=!count||busy;
 }

 async function media(file){
  if(cache.has(file.id))return cache.get(file.id);
  const data=await api('/api/conversion/workflow/'+file.id+'/media');cache.set(file.id,data);failed.delete(file.id);return data;
 }
 async function probeVisible(){
  if(activeProbe||!mode)return;activeProbe=true;
  try{for(const file of visible()){
   if(!mode||location.hash!=='#conversion')break;
   if(cache.has(file.id)||failed.has(file.id))continue;
   try{await media(file);}catch(e){failed.add(file.id);}
   if(!$('cw-dialog').open)renderFilms();
  }}finally{activeProbe=false;}
 }
 function renderFilms(){
  const list=$('cw-films');list.replaceChildren();
  const found=visible();$('cw-status').textContent=found.length+' film · '+labels[mode]+' · Største besparelse først'+(mode==='audio'?'':' (20 Mbps)');
  if(!found.length)list.append(node('p','Ingen film matcher dette valg. Prøv søgningen eller vis oversprungne og konverterede film.','muted'));
  for(const file of found.slice(0,limit)){
   const row=node('article',null,'cw-film'),check=node('input');row.dataset.fileId=file.id;check.type='checkbox';check.checked=selected.has(file.id);check.disabled=busy||!file.eligible||file.skipped_modes?.includes(mode)||file.completed_modes?.includes(mode);check.title=file.completed_modes?.includes(mode)?'Allerede behandlet i denne liste':file.skipped_modes?.includes(mode)?'Sprunget over i denne liste':!file.eligible?(file.reason||'Kan ikke v\u00e6lges lige nu'):'';check.setAttribute('aria-label','Vælg '+file.title);check.onchange=()=>{check.checked?selected.add(file.id):selected.delete(file.id);selection();};
   const cover=file.cover?node('img'):node('span','▣');cover.className='cw-cover';if(file.cover){cover.src=file.cover;cover.alt='';cover.loading='lazy';}
   const info=node('div',null,'cw-film-info');info.append(node('h3',file.title),node('p',size(file.size)+' · '+file.name,'muted small'));
   const tags=node('p',null,'muted small');
   const completed=file.completed_modes||[];
   tags.textContent=[file.source==='manual'?(file.torrent_status==='ambiguous'?'Flere mulige torrents \u00b7 originalen bevares':'Manuelt tilf\u00f8jet \u00b7 uden tilknyttet torrent'):'',completed.includes('full')?'Video og lyd gennemgået':completed.map(m=>labels[m]+' konverteret').join(' · '),file.skipped_modes?.includes(mode)?'Sprunget over i denne liste':!completed.includes(mode)?'Ikke gennemgået i denne liste':''].filter(Boolean).join(' · ');info.append(tags);
   if(completed.includes(mode))row.classList.add('cw-completed');
   const estimatePanel=node('div',null,'cw-film-estimates');
   const data=cache.get(file.id)?.media||file.media;
   if(data){
    if(mode!=='audio'){const v=streams(file,'video')[0]||{},dv=v.side_data_list?.find(s=>s.side_data_type==='DOVI configuration record');info.append(node('p',[v.codec_name?.toUpperCase(),v.width&&v.width+' × '+v.height,dv?'Dolby Vision '+dv.dv_profile+(dv.dv_profile===8?'.'+dv.dv_bl_signal_compatibility_id:''):'Ingen Dolby Vision'].filter(Boolean).join(' · '),'small'));}
    if(mode!=='video')info.append(node('p',streams(file,'audio').map(streamLabel).join(' / ')||'Ingen lydspor','small'));
    const estimates=node('div',null,'cw-estimates'),opts=defaults(file);
    for(const rate of mode==='audio'?[null]:[20,30,40]){if(rate)opts.bitrate=rate;estimates.append(estimateCard(file,opts,rate?rate+' Mbps':'Lydvalg'));}
    estimatePanel.append(node('p','Estimat efter konvertering · Original: '+size(file.size),'cw-estimates-heading'),estimates);
   }else estimatePanel.append(node('p',failed.has(file.id)?'Medieoplysninger kunne ikke læses.':'Læser formater og størrelsesestimater …','muted small'));
   if(failed.has(file.id))info.append(button('Prøv medieoplysninger igen',()=>{failed.delete(file.id);probeVisible();},'quiet'));
   if(!file.eligible||file.source==='manual')info.append(node('p',file.reason||'Originalen gemmes i Originals, medmindre du v\u00e6lger sletning efter konvertering.','muted small'));
   const skipped=file.skipped_modes?.includes(mode),skip=button(skipped?'Gendan':'Spring over',async()=>{
    skip.disabled=true;try{await post('skip',{id:file.id,mode,skip:!skipped});file.skipped_modes=(file.skipped_modes||[]).filter(m=>m!==mode);if(!skipped)file.skipped_modes.push(mode);selected.delete(file.id);renderFilms();}catch(e){error('cw-error',e.message);skip.disabled=false;}
   },'quiet');row.append(check,cover,info,estimatePanel,skip);list.append(row);
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
  try{const data=await api('/api/conversion/workflow');items=data.items||[];jobs=data.jobs||[];for(const file of items){if(file.fingerprint&&JSON.stringify(cache.get(file.id)?.fingerprint)!==JSON.stringify(file.fingerprint))cache.delete(file.id);}for(const id of selected)if(!items.some(i=>i.id===id&&i.eligible&&!i.completed_modes?.includes(mode)&&!i.skipped_modes?.includes(mode)))selected.delete(id);if(mode){renderFilms();probeVisible();}renderJobs();}
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
   fields.append(queueTimeCard());
   review.forEach((r,i)=>{const div=node('div',null,'cw-review-item');div.append(node('strong',r.file.title),node('p',labels[mode]+(mode==='audio'?'':' · '+r.options.bitrate+' Mbps')+(mode==='video'?'':' · '+audioSummary(r.options))),estimateCard(r.file,r.options,'Original: '+size(r.file.size)),timeCard(r.file,r.options),node('p',r.file.source==='manual'?(r.file.torrent_status==='ambiguous'?'Originalen bevares p\u00e5 sin plads':r.options.delete_original?'Originalen slettes efter kontrol':'Originalen gemmes i Originals'):actions.find(a=>a[0]===r.policy.ratio_action)[1],'muted small'),button('Ret indstillinger',()=>{step=i;showStep();},'quiet'));fields.append(div);});
   fields.append(node('p','Filmene behandles én ad gangen på serveren. Film uden torrent får en separat resultatfil. Originalen gemmes i Originals eller slettes efter dit valg. Torrentoriginaler flyttes efter kontrol gennem qBittorrent til Seeder med optjent ratio og seedtid bevaret.','muted small'));return;
  }
  const current=review[step],file=current.file,o=current.options,p=current.policy;
  $('cw-step').textContent=labels[mode]+' · FILM '+(step+1)+' AF '+review.length;$('cw-dialog-title').textContent=file.title;$('cw-next').textContent=step===review.length-1?'Gennemse kø →':'Næste film →';$('cw-next').disabled=false;
  const live=node('div',null,'cw-live');live.setAttribute('aria-live','polite');
  function update(){live.replaceChildren(estimateCard(file,o,(mode==='audio'?'Lydvalg':o.bitrate+' Mbps')+' · Original: '+size(file.size)),timeCard(file,o),node('small',file.source==='manual'?(file.torrent_status==='ambiguous'?'Originalen bevares p\u00e5 sin plads.':o.delete_original?'Originalen slettes efter kontrol og lagring af resultatfilen.':'Originalen flyttes til Originals efter kontrol. Begge filer optager plads, indtil du selv rydder op.'):'Originalen bevares i Seeder. Estimatet er ikke en garanti og omfatter ikke originalens ekstra plads.'));}
  if(mode!=='audio'){
   const video=fieldset('Video'),grid=node('div',null,'cw-field-grid');grid.append(select('Videobitrate',[[20,'20 Mbps'],[30,'30 Mbps'],[40,'40 Mbps']],o.bitrate,v=>{o.bitrate=Number(v);update();}),select('Dolby Vision', [['separate','Fjern fra filmen · gem separat (HDR10)'],['preserve','Behold · profil 8.1']],o.dolby_vision_mode,v=>{o.dolby_vision_mode=v;update();}));video.append(grid,node('p','Profil 7 og 8.1 kan behandles. Profil 7 bliver 8.1; det ekstra billedlag følger kun med originalen. Filer uden Dolby Vision påvirkes ikke.','muted small'));fields.append(video);
  }
  if(mode!=='video'){
   const audio=fieldset('Behold lyd');
   audio.append(node('p','De afkrydsede originalspor beholdes uændret. Alle er valgt fra start.','muted small'));
   const formats=fieldset('Konvertér lyd'),preview=node('div');preview.setAttribute('aria-live','polite');
   const refreshAudio=()=>{
    preview.replaceChildren();
    for(const s of streams(file,'audio'))for(const codec of missingCodecs(s,o))preview.append(node('p',streamLabel(s)+' → '+codecNames[codec],'muted small'));
    if(!preview.childElementCount)preview.append(node('p','Ingen nye lydspor valgt.','muted small'));
    preview.prepend(node('strong','Resultat: '+audioSummary(o)));
    update();
   };
   trackChoices(file,'audio',o,audio,refreshAudio);
   formats.append(node('p','Vælg AC3, E-AC3 eller begge ud for hvert sprog/spor. Konvertering er uafhængig af “Behold lyd”: fjern markeringen dér, hvis du kun vil have den konverterede version.','muted small'));
   for(const s of streams(file,'audio')){
    const group=fieldset(streamLabel(s));
    for(const codec of ['eac3','ac3']){
     const row=node('label',null,'check-label'),check=node('input');check.type='checkbox';check.checked=missingCodecs(s,o).includes(codec);
     const exists=s.codec_name===codec;check.disabled=exists||!supportedAudio(s);
     check.onchange=()=>{const chosen=new Set(o.audio_conversions[s.index]||[]);check.checked?chosen.add(codec):chosen.delete(codec);o.audio_conversions[s.index]=['eac3','ac3'].filter(c=>chosen.has(c));refreshAudio();};
     row.append(check,node('span',codecNames[codec]+(exists?' · findes allerede':!supportedAudio(s)?' · kanalopsætningen understøttes ikke':'')));group.append(row);
    }
    formats.append(group);
   }
   formats.append(preview,node('p','Sprog og kanalantal bevares, herunder 5.1. Spor over 5.1 eller med ukendt kanalopsætning kan beholdes som original lyd.','muted small'));
   fields.append(audio,formats);refreshAudio();
  }
  if(mode==='full'){const subs=fieldset('Undertekster');trackChoices(file,'subtitle',o,subs,update);if(!streams(file,'subtitle').length)subs.append(node('p','Ingen indbyggede undertekster.','muted'));fields.append(subs);}
  if(file.source==='manual'){
   const original=fieldset('Originalen efter konvertering');
   if(file.torrent_status==='ambiguous')original.append(node('p','Flere torrents kan bruge denne fil. Originalen bevares p\u00e5 sin plads; resultatet gemmes separat.','muted small'));
   else original.append(select('Originalfil', [['keep','Behold originalen i Originals'],['delete','Slet originalen efter konvertering']],o.delete_original?'delete':'keep',value=>{o.delete_original=value==='delete';update();}),node('p','Originalen flyttes eller slettes f\u00f8rst, n\u00e5r resultatfilen er kontrolleret og gemt. Beholdte originaler ligger i mappen Originals ved siden af Seeder, med samme undermapper som f\u00f8r.','muted small'));
   fields.append(original);fields.prepend(live);update();return;
  }
  const original=fieldset('Originalen efter konvertering'),extra=node('div');
  function policyFields(){extra.replaceChildren();if(!['keep','stop_keep'].includes(p.ratio_action)){
   const timed=p.ratio_action==='delete_time',label=node('label',timed?'Aktiv seedtid i minutter':'Målratio'),input=node('input');input.type='number';input.min=1;input.max=timed?525600:10000;input.step=timed?'1':'any';input.required=true;input.value=timed?p.seed_minutes:p.ratio_limit;input.oninput=()=>{p[timed?'seed_minutes':'ratio_limit']=Number(input.value);};label.append(input);extra.append(label,node('p',timed?'Når målet er nået, slettes original og torrent, også ved aktive downloadere. Optjent aktiv seedtid tæller med.':'Målene bruger reel upload og aktiv seedtid. Pauser og flytning tæller ikke. Oprydning venter på aktive downloadere.','muted small'));}}
  original.append(select('Seeding og oprydning',actions,p.ratio_action,v=>{p.ratio_action=v;policyFields();}),extra,node('p','Kun originalen i Seeder er omfattet af oprydning. Den konverterede film bliver i biblioteket. Flere film i samme torrent skal have samme seedingvalg, fordi qBittorrent håndterer hele torrenten.','muted small'));policyFields();fields.append(original);fields.prepend(live);update();
 }
 function validCurrent(){if(step>=review.length)return true;const r=review[step],o=r.options,audio=streams(r.file,'audio');if(mode!=='video'&&audio.length&&!o.audio.length&&!audio.some(s=>missingCodecs(s,o).length)){error('cw-dialog-error','Vælg mindst ét lydspor at beholde eller konvertere.');return false;}if(audio.some(s=>missingCodecs(s,o).length&&!supportedAudio(s))){error('cw-dialog-error','Et valgt spor har en kanalopsætning, der ikke understøttes. Behold det som original lyd.');return false;}return true;}
 $('cw-configure').onclick=async()=>{
  if(busy)return;busy=true;$('cw-configure').disabled=true;error('cw-error','');
  try{review=[];for(const file of items.filter(f=>selected.has(f.id)).sort(compareSavings)){const data=await media(file);review.push({file,fingerprint:data.fingerprint,options:defaults(file),policy:{ratio_action:'keep',ratio_limit:1,seed_minutes:60}});}step=0;showStep();$('cw-dialog').showModal();}
  catch(e){error('cw-error',e.message);}finally{busy=false;selection();}
 };
 $('cw-form').onsubmit=async e=>{e.preventDefault();if(busy||!validCurrent())return;if(step<review.length){step++;showStep();return;}busy=true;$('cw-next').disabled=true;
  try{await post('queue',{items:review.map(r=>({id:r.file.id,options:r.options,policy:r.policy,fingerprint:r.fingerprint}))});$('cw-dialog').close();selected.clear();await load();}
  catch(e){error('cw-dialog-error',e.message);}finally{busy=false;$('cw-next').disabled=false;}
 };
 $('cw-clear-selected').onclick=()=>{selected.clear();renderFilms();$('cw-search').focus();};
 $('cw-skip-selected').onclick=async()=>{
  if(busy||!selected.size)return;busy=true;renderFilms();error('cw-error','');
  const ids=[...selected];try{await post('skip',{ids,mode,skip:true});for(const file of items.filter(f=>ids.includes(f.id))){file.skipped_modes=[...new Set([...(file.skipped_modes||[]),mode])];}selected.clear();}
  catch(e){error('cw-error',e.message);}finally{busy=false;renderFilms();}
 };
 $('cw-prev').onclick=()=>{if(step>0){step--;showStep();}};
 $('cw-skip-film').onclick=async()=>{if(busy)return;busy=true;const file=review[step].file;try{await post('skip',{id:file.id,mode,skip:true});file.skipped_modes=[...(file.skipped_modes||[]).filter(m=>m!==mode),mode];selected.delete(file.id);review.splice(step,1);showStep();renderFilms();}catch(e){error('cw-dialog-error',e.message);}finally{busy=false;}};
 $('cw-close').onclick=()=>{if(!busy)$('cw-dialog').close();};$('cw-dialog').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 document.querySelectorAll('#cw-cards [data-mode]').forEach(card=>card.onclick=()=>{mode=card.dataset.mode;selected.clear();limit=40;$('cw-cards').hidden=true;$('cw-library').hidden=false;$('cw-title').textContent=labels[mode];renderFilms();load();});
 $('cw-back').onclick=()=>{mode=null;selected.clear();$('cw-cards').hidden=false;$('cw-library').hidden=true;};
 $('cw-search').oninput=()=>{limit=40;renderFilms();probeVisible();};$('cw-show-completed').onchange=()=>{renderFilms();probeVisible();};$('cw-show-skipped').onchange=()=>{renderFilms();probeVisible();};
 $('cw-refresh').onclick=()=>{failed.clear();cache.clear();load();};$('cw-queue-refresh').onclick=load;
 window.addEventListener('hashchange',()=>{if(location.hash==='#conversion')load();});
 setInterval(()=>{if(location.hash==='#conversion'&&!document.hidden&&!$('cw-dialog').open&&!busy)load();},15000);
 if(location.hash==='#conversion')load();
})();
