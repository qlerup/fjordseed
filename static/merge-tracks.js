(() => {
 const $=id=>document.getElementById(id), node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
 if(!$('mt-open'))return;
 const button=(text,fn,cls='secondary')=>{const e=node('button',text,cls);e.type='button';e.onclick=fn;return e;};
 const post=(path,data={})=>api('/api/merge/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 const error=text=>{const id=$('mt-dialog').open?'mt-dialog-error':'mt-error';$(id).textContent=text||'';$(id).hidden=!text;};
 let items=[],base=null,donor=null,stage='base',busy=false,open=false,limit=40,loading=false,jobsLoading=false;
 const choices={base:new Set(),donor:new Set()}, originals={base:null,donor:null};
 const originalActions=[['keep','Behold original · seed indtil du stopper'],['stop_keep','Behold original · stop efter fletning'],['delete','Slet original ved målratio eller 50 timers seedtid'],['automatic','Optimér upload · slet original bagefter'],['delete_ratio','Slet original kun ved målratio'],['delete_time','Seed i X minutter · slet original bagefter']];
 const originalDefault=file=>file.source==='torrent'?{policy:{ratio_action:'keep',ratio_limit:1,seed_minutes:60}}:{disposition:'archive'};
 const sizes=n=>new Intl.NumberFormat('da-DK',{maximumFractionDigits:1}).format(n/1024**3)+' GB';
 const duration=n=>n?Math.floor(n/60)+' min '+Math.round(n%60)+' sek':'Ukendt varighed';
 const label=t=>[t.language,t.codec,t.profile,t.channels?t.channels+' kanaler':'',t.title,t.default?'Standard':'',t.forced?'Tvungen':''].filter(Boolean).join(' · ');
 function syncSelection(){window.dispatchEvent(new CustomEvent('fjord-merge-selection',{detail:{base,donor,stage:base&&donor&&stage!=='base'?'tracks':'base',active:stage==='sync',choices:{base:[...choices.base],donor:[...choices.donor]}}}));}
 function updateSummary(){
  const selected=[...(base?.tracks||[]).filter(t=>choices.base.has(t.id)),...(donor?.tracks||[]).filter(t=>choices.donor.has(t.id))];
  $('mt-summary').textContent='Resultat: hovedfilens video · '+selected.filter(t=>t.kind==='audio').length+' lydspor · '+selected.filter(t=>t.kind==='subtitles').length+' undertekstspor';
  $('mt-submit').disabled=busy||!choices.donor.size;$('mt-next').disabled=busy||!choices.donor.size;syncSelection();
 }
 function renderPicker(){
  const isDonor=stage==='donor',list=$(isDonor?'mt-donor-films':'mt-films'),search=$(isDonor?'mt-donor-search':'mt-search').value.toLocaleLowerCase();list.replaceChildren();
  const found=items.filter(f=>(!isDonor||f.id!==base?.id)&&(f.title+' '+f.name).toLocaleLowerCase().includes(search)).sort((a,b)=>a.title.localeCompare(b.title,'da'));
  if(!found.length)list.append(node('p','Ingen film fundet. Prøv en anden søgning eller opdater biblioteket.','muted'));
  for(const file of found.slice(0,limit)){
   const row=node('article',null,'mt-film'),info=node('div');info.append(node('h3',file.title),node('p',file.name+' · '+sizes(file.size),'muted small'));
   if(!file.eligible)info.append(node('p','Vent til download eller konvertering er færdig. Filer med flere mulige torrents kan ikke vælges.','muted small'));
   const choose=button(isDonor?'Hent spor herfra':'Brug som hovedfil',()=>chooseFile(file));choose.disabled=busy||!file.eligible;choose.setAttribute('aria-label',(isDonor?'Hent spor fra: ':'Brug som hovedfil: ')+file.name);row.append(info,choose);list.append(row);
  }
  if(found.length>limit)list.append(button('Vis flere film',()=>{limit+=40;renderPicker();}));
 }
 function renderSources(){
  const sources=$('mt-sources');sources.replaceChildren();
  for(const [key,file,title] of [['base',base,'Behold fra hovedfilen'],['donor',donor,'Tilføj fra den anden fil']]){
   const panel=node('section',null,'mt-source'),change=button('Skift fil',()=>{if(busy)return;if(key==='base'){$('mt-dialog').close();return;}stage='donor';$('mt-donor-search').value='';show();},'quiet');change.disabled=busy;
   panel.append(node('p',key==='base'?'VIDEO + VALGTE SPOR':'KUN VALGTE SPOR','eyebrow'),node('h3',title),node('p',file.name),node('p',duration(file.duration)+' · '+sizes(file.size),'muted small'),change);
   for(const [kind,name] of [['audio','Lydspor'],['subtitles','Undertekster']]){
    const field=node('fieldset');field.append(node('legend',name));const tracks=file.tracks.filter(t=>t.kind===kind);
    if(!tracks.length)field.append(node('p','Ingen '+name.toLowerCase()+' i filen.','muted small'));
    for(const track of tracks){const row=node('label',null,'check-label'),check=node('input');check.type='checkbox';check.checked=choices[key].has(track.id);check.disabled=busy;check.onchange=()=>{check.checked?choices[key].add(track.id):choices[key].delete(track.id);updateSummary();};row.append(check,node('span',label(track)));field.append(row);}panel.append(field);
   }
   sources.append(panel);
  }
 }
 function originalFields(key,file){
  const field=node('fieldset'),title=key==='base'?'Originalen fra hovedfilen':'Originalen fra den anden fil';field.append(node('legend',title));
  const o=originals[key]||(originals[key]=originalDefault(file)),label=node('label',file.source==='torrent'?'Seeding og oprydning':'Originalfil'),select=node('select'),extra=node('div');select.id='mt-original-'+key;select.disabled=busy;
  const actions=file.source==='torrent'?originalActions:[['archive','Behold originalen i Originals'],['delete','Slet originalen efter fletning']];
  for(const [value,text] of actions){const option=node('option',text);option.value=value;select.append(option);}select.value=o.policy?o.policy.ratio_action:o.disposition;
  function sync(){if(file.torrent_hash){const other=key==='base'?'donor':'base',otherFile=other==='base'?base:donor;if(otherFile?.torrent_hash===file.torrent_hash){originals[other]=o;const input=$('mt-original-'+other)?.closest('fieldset').querySelector('input');if(input)input.value=o.policy.ratio_action==='delete_time'?o.policy.seed_minutes:o.policy.ratio_limit;}}}
  function inputs(){extra.replaceChildren();if(o.policy&&!['keep','stop_keep'].includes(o.policy.ratio_action)){
   const timed=o.policy.ratio_action==='delete_time',l=node('label',timed?'Aktiv seedtid i minutter':'Målratio'),input=node('input');input.type='number';input.min=1;input.max=timed?525600:10000;input.step=timed?'1':'any';input.required=true;input.disabled=busy;input.value=timed?o.policy.seed_minutes:o.policy.ratio_limit;input.oninput=()=>{o.policy[timed?'seed_minutes':'ratio_limit']=Number(input.value);sync();};l.append(input);extra.append(l,node('p',timed?'Optjent aktiv seedtid tæller med. Når målet er nået, slettes original og torrent, også ved aktive downloadere.':'Reel upload og aktiv seedtid tæller med. Oprydning venter på aktive downloadere.','muted small'));
  }}
  select.onchange=()=>{if(o.policy)o.policy.ratio_action=select.value;else o.disposition=select.value;sync();renderReview();};label.append(select);field.append(label,extra,node('p',o.policy?'Originalen flyttes via qBittorrent til Seeder. Valget gælder kun originalen; den flettede film bliver i biblioteket. Filer i samme torrent følger samme valg.':'Originalen flyttes til Originals eller slettes først, når resultatfilen er kontrolleret og gemt.','muted small'));inputs();return field;
 }
 function renderReview(){
  const list=$('mt-review-details');list.replaceChildren();
  for(const [key,file,title] of [['base',base,'Video og beholdte spor fra hovedfilen'],['donor',donor,'Nye spor fra den anden fil']]){
   const section=node('section',null,'mt-review-file');section.append(node('h4',title),node('p',file.name,'muted small'));
   const kept=file.tracks.filter(t=>choices[key].has(t.id)),audio=kept.filter(t=>t.kind==='audio'),subs=kept.filter(t=>t.kind==='subtitles');
   section.append(node('p',audio.length+' lydspor'));const tracks=node('ul');for(const t of audio)tracks.append(node('li',label(t)));section.append(tracks);
   const details=node('details');details.append(node('summary',subs.length+' undertekstspor'));const subtitles=node('ul');for(const t of subs)subtitles.append(node('li',label(t)));details.append(subtitles);section.append(details,originalFields(key,file));list.append(section);
  }
  const offset=Number($('mt-offset').value);list.append(node('p','Forskydning af nye spor: '+(offset>0?'+':'')+offset+' ms','mt-review-offset'));
 }
 function show(){
  $('mt-back').disabled=busy;$('mt-refresh').disabled=busy;$('mt-close').disabled=busy;$('mt-prev').disabled=busy;
  if(stage==='base'){
   if($('mt-dialog').open)$('mt-dialog').close();document.documentElement.classList.remove('mt-modal-open');$('mt-form').hidden=true;syncSelection();renderPicker();return;
  }
  if(!$('mt-dialog').open){$('mt-dialog').showModal();document.documentElement.classList.add('mt-modal-open');}
  const steps=['donor','tracks','sync','review'];
  for(const id of steps){const e=$('mt-step-'+id);e.removeAttribute('aria-current');if(stage===id)e.setAttribute('aria-current','step');}
  $('mt-dialog-step').textContent='TRIN '+(steps.indexOf(stage)+1)+' AF 4';$('mt-base-name').textContent='Hovedfil: '+base.name;
  $('mt-dialog-title').textContent=({donor:'Vælg filen med ekstra spor',tracks:'Vælg spor til den nye film',sync:'Test videoen med det nye lydspor',review:'Gennemse og start fletningen'})[stage];
  $('mt-donor-picker').hidden=stage!=='donor';$('mt-form').hidden=stage==='donor';
  $('mt-track-step').hidden=stage!=='tracks';$('mt-sync-step').hidden=stage!=='sync';$('mt-review-step').hidden=stage!=='review';
  $('mt-submit').hidden=stage!=='review';$('mt-next').hidden=stage==='review';$('mt-next').textContent=stage==='tracks'?'Næste: test video og lyd →':'Gennemse fletningen →';
  if(stage==='donor'){syncSelection();renderPicker();$('mt-donor-search').focus();}
  else{
   if(stage==='tracks')renderSources();if(stage==='review')renderReview();
   const difference=Math.abs(base.duration-donor.duration),warning=$('mt-duration-warning');warning.hidden=!base.duration||!donor.duration||difference<1;
   warning.textContent='Filerne har forskellig varighed: '+duration(base.duration)+' og '+duration(donor.duration)+'. Kontrollér klipningen med lydmatch og prøveklip. En fast forskydning kan ikke rette forskellige scener.';
   updateSummary();$('mt-dialog-title').focus();
  }
  $('mt-dialog').scrollTop=0;
 }
 async function chooseFile(file){
  if(busy)return;busy=true;$('mt-close').disabled=true;error('');const requested=stage,status=$(requested==='donor'?'mt-donor-status':'mt-status');status.textContent='Læser spor fra '+file.name+' …';renderPicker();
  try{
   const detail=await api('/api/merge/library/'+encodeURIComponent(file.id));if(!open)return;
   if(requested==='base'){base=detail;originals.base=originalDefault(detail);originals.donor=null;choices.base=new Set(detail.tracks.map(t=>t.id));donor=null;choices.donor.clear();stage='donor';}
   else{donor=detail;originals.donor=base.torrent_hash&&base.torrent_hash===detail.torrent_hash?originals.base:originalDefault(detail);choices.donor=new Set();stage='tracks';}
   $('mt-donor-search').value='';limit=40;
  }catch(e){error(e.message);}finally{busy=false;status.textContent='';if(open)show();}
 }
 async function loadLibrary(){
  if(loading)return;loading=true;error('');$('mt-status').textContent='Henter bibliotek …';
  try{const data=await api('/api/merge/library');items=data.items||[];$('mt-status').textContent=items.length+' filer'+(data.truncated?' · Listen er begrænset til 5.000 filer':'');if(['base','donor'].includes(stage))renderPicker();}
  catch(e){error(e.message);$('mt-status').textContent='Biblioteket kunne ikke indlæses.';}finally{loading=false;}
 }
 async function loadJobs(){
  if(jobsLoading)return;jobsLoading=true;
  try{
   const data=await api('/api/merge/jobs'),list=$('mt-jobs');list.replaceChildren();if(!data.jobs?.length)list.append(node('p','Ingen filer i flettekøen.','muted'));
   for(const job of data.jobs||[]){
    const row=node('div',null,'cw-job'),copy=node('div'),phase={copying:'Kopierer',verifying:'Kontrollerer',finalizing:'Flytter og gemmer',refresh:'Opdaterer biblioteker'}[job.phase];copy.append(node('strong',job.name),node('p',job.state==='running'&&phase?phase:({queued:'Venter',running:'Fletter',done:'Færdig',error:'Kræver kontrol',cancelled:'Annulleret'})[job.state]||job.state,'small'),node('p',job.detail,'muted small'));
    if(job.state==='running'){const progress=node('progress');progress.max=100;if(Number.isFinite(job.progress))progress.value=job.progress;progress.setAttribute('aria-label',(job.phase==='copying'?'Kopiering af ':'Fletning af ')+job.name);copy.append(progress);if(Number.isFinite(job.progress))copy.append(node('p',job.progress.toLocaleString('da-DK')+' %'+(job.phase==='copying'?' af kopieringen':''),'muted small'));
     if(Number.isFinite(job.copied_bytes)&&Number.isFinite(job.total_bytes)){const gb=value=>(value/1e9).toLocaleString('da-DK',{minimumFractionDigits:1,maximumFractionDigits:1});let text=gb(job.copied_bytes)+' af '+gb(job.total_bytes)+' GB';if(Number.isFinite(job.eta_seconds)){const seconds=Math.max(0,Math.ceil(job.eta_seconds));text+=' · ca. '+(seconds>=60?Math.ceil(seconds/60)+' min':seconds+' sek')+' tilbage i kopieringen';}copy.append(node('p',text,'muted small'));}
    }
    row.append(copy);const action=async kind=>{try{await post('jobs/'+job.id+'/'+kind);await loadJobs();}catch(e){error(e.message);}};
    if(['queued','error'].includes(job.state)&&!['finalizing','refresh'].includes(job.phase))row.append(button('Fjern fra kø',()=>action('cancel'),'quiet'));if(job.state==='error')row.append(button('Prøv igen',()=>action('retry')));list.append(row);
   }
  }catch(e){error(e.message);}finally{jobsLoading=false;}
 }
 function advance(){if(busy)return;error('');if(!choices.donor.size){error('Vælg mindst ét spor fra den anden fil.');return;}const offset=Number($('mt-offset').value);if(!Number.isInteger(offset)||Math.abs(offset)>3600000){error('Angiv tidsforskydningen i hele millisekunder.');return;}stage=stage==='tracks'?'sync':'review';show();}
 $('mt-open').onclick=()=>{open=true;$('cw-cards').hidden=true;$('mt-panel').hidden=false;show();loadLibrary();loadJobs();};
 $('mt-back').onclick=()=>{if(busy)return;open=false;if($('mt-dialog').open)$('mt-dialog').close();$('mt-panel').hidden=true;$('cw-cards').hidden=false;};
 $('mt-close').onclick=()=>{if(!busy)$('mt-dialog').close();};$('mt-change-base').onclick=()=>{if(!busy)$('mt-dialog').close();};
 $('mt-dialog').addEventListener('cancel',event=>{if(busy)event.preventDefault();});
 $('mt-dialog').addEventListener('close',()=>{stage='base';document.documentElement.classList.remove('mt-modal-open');$('mt-dialog-error').hidden=true;$('mt-dialog-error').textContent='';show();});
 $('mt-next').onclick=advance;$('mt-prev').onclick=()=>{if(!busy){error('');stage=({tracks:'donor',sync:'tracks',review:'sync'})[stage]||'donor';show();}};
 for(const id of ['mt-search','mt-donor-search'])$(id).oninput=()=>{limit=40;renderPicker();};
 $('mt-refresh').onclick=()=>{if(!busy)loadLibrary();};$('mt-jobs-refresh').onclick=loadJobs;
 window.addEventListener('hashchange',()=>{if(location.hash!=='#conversion'&&$('mt-dialog').open)$('mt-dialog').close();});
 $('mt-form').onsubmit=async event=>{
  event.preventDefault();if(busy)return;if(stage!=='review'){advance();return;}error('');if(!choices.donor.size){error('Vælg mindst ét spor fra den anden fil.');return;}
  const offset=Number($('mt-offset').value);if(!Number.isInteger(offset)||Math.abs(offset)>3600000){error('Angiv tidsforskydningen i hele millisekunder.');return;}
  if(!$('mt-form').reportValidity())return;
  busy=true;show();
  try{
   const selection=(file,key)=>({id:file.id,fingerprint:file.fingerprint,tracks:[...choices[key]],original:originals[key]});
   const result=await post('queue',{base:selection(base,'base'),donor:selection(donor,'donor'),offset_ms:offset});
   base=null;donor=null;choices.base.clear();choices.donor.clear();stage='base';$('mt-offset').value='0';$('mt-status').textContent='Tilføjet til køen · '+result.output;$('mt-dialog').close();await loadJobs();
  }catch(e){error(e.message);}finally{busy=false;show();}
 };
 setInterval(()=>{if(open&&location.hash==='#conversion'&&!document.hidden)loadJobs();},3000);
})();
