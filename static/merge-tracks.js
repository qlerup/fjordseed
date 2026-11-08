(() => {
 const $=id=>document.getElementById(id), node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
 if(!$('mt-open'))return;
 const button=(text,fn,cls='secondary')=>{const e=node('button',text,cls);e.type='button';e.onclick=fn;return e;};
 const post=(path,data={})=>api('/api/merge/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 const error=text=>{$('mt-error').textContent=text||'';$('mt-error').hidden=!text;};
 let items=[],base=null,donor=null,stage='base',busy=false,open=false,limit=40,loading=false,jobsLoading=false;
 const choices={base:new Set(),donor:new Set()};
 const sizes=n=>new Intl.NumberFormat('da-DK',{maximumFractionDigits:1}).format(n/1024**3)+' GB';
 const duration=n=>n?Math.floor(n/60)+' min '+Math.round(n%60)+' sek':'Ukendt varighed';
 const label=t=>[t.language,t.codec,t.profile,t.channels?t.channels+' kanaler':'',t.title,t.default?'Standard':'',t.forced?'Tvungen':''].filter(Boolean).join(' · ');
 function updateSummary(){
  const selected=[...(base?.tracks||[]).filter(t=>choices.base.has(t.id)),...(donor?.tracks||[]).filter(t=>choices.donor.has(t.id))];
  $('mt-summary').textContent='Resultat: hovedfilens video · '+selected.filter(t=>t.kind==='audio').length+' lydspor · '+selected.filter(t=>t.kind==='subtitles').length+' undertekstspor';
  $('mt-submit').disabled=busy||!choices.donor.size;
 }
 function renderPicker(){
  const list=$('mt-films');list.replaceChildren();const search=$('mt-search').value.toLocaleLowerCase();
  const found=items.filter(f=>(stage!=='donor'||f.id!==base?.id)&&(f.title+' '+f.name).toLocaleLowerCase().includes(search)).sort((a,b)=>a.title.localeCompare(b.title,'da'));
  if(!found.length)list.append(node('p','Ingen film fundet. Prøv en anden søgning eller opdater biblioteket.','muted'));
  for(const file of found.slice(0,limit)){
   const row=node('article',null,'mt-film'),info=node('div');info.append(node('h3',file.title),node('p',file.name+' · '+sizes(file.size),'muted small'));
   if(!file.eligible)info.append(node('p','Vent til download eller konvertering er færdig. Filer med flere mulige torrents kan ikke vælges.','muted small'));
   const choose=button(stage==='base'?'Brug som hovedfil':'Hent spor herfra',()=>chooseFile(file));choose.disabled=busy||!file.eligible;choose.setAttribute('aria-label',(stage==='base'?'Brug som hovedfil: ':'Hent spor fra: ')+file.name);
   row.append(info,choose);list.append(row);
  }
  if(found.length>limit)list.append(button('Vis flere film',()=>{limit+=40;renderPicker();}));
 }
 function show(){
  $('mt-back').disabled=busy;$('mt-refresh').disabled=busy;
  $('mt-picker').hidden=stage==='tracks';$('mt-form').hidden=stage!=='tracks';
  for(const id of ['base','donor','tracks']){const e=$('mt-step-'+id);e.removeAttribute('aria-current');if(stage===id)e.setAttribute('aria-current','step');}
  $('mt-picker-title').textContent=stage==='base'?'Hvilken film skal levere billedet?':'Hvilken fil vil du hente ekstra spor fra?';
  $('mt-picked').replaceChildren();if(base&&stage==='donor')$('mt-picked').append(node('span','Hovedfil: '+base.name+' '),button('Skift hovedfil',()=>{stage='base';show();},'quiet'));
  if(stage!=='tracks'){renderPicker();return;}
  const sources=$('mt-sources');sources.replaceChildren();
  for(const [key,file,title] of [['base',base,'Behold fra hovedfilen'],['donor',donor,'Tilføj fra den anden fil']]){
   const panel=node('section',null,'mt-source'),change=button('Skift fil',()=>{if(busy)return;stage=key;$('mt-search').value='';show();},'quiet');change.disabled=busy;
   panel.append(node('p',key==='base'?'VIDEO + VALGTE SPOR':'KUN VALGTE SPOR','eyebrow'),node('h3',title),node('p',file.name),node('p',duration(file.duration)+' · '+sizes(file.size),'muted small'),change);
   for(const [kind,name] of [['audio','Lydspor'],['subtitles','Undertekster']]){
    const field=node('fieldset');field.append(node('legend',name));const tracks=file.tracks.filter(t=>t.kind===kind);
    if(!tracks.length)field.append(node('p','Ingen '+name.toLowerCase()+' i filen.','muted small'));
    for(const track of tracks){const row=node('label',null,'check-label'),check=node('input');check.type='checkbox';check.checked=choices[key].has(track.id);check.disabled=busy;check.onchange=()=>{check.checked?choices[key].add(track.id):choices[key].delete(track.id);updateSummary();};row.append(check,node('span',label(track)));field.append(row);}
    panel.append(field);
   }
   sources.append(panel);
  }
  const difference=Math.abs(base.duration-donor.duration),warning=$('mt-duration-warning');warning.hidden=!base.duration||!donor.duration||difference<1;
  warning.textContent='Filerne har forskellig varighed: '+duration(base.duration)+' og '+duration(donor.duration)+'. Kontrollér, at det er samme klipning; sporene synkroniseres ikke automatisk.';
  updateSummary();
 }
 async function chooseFile(file){
  if(busy)return;busy=true;error('');$('mt-status').textContent='Læser spor fra '+file.name+' …';renderPicker();const requested=stage;
  try{
   const detail=await api('/api/merge/library/'+encodeURIComponent(file.id));
   if(!open)return;
   if(requested==='base'){
    base=detail;choices.base=new Set(detail.tracks.map(t=>t.id));
    if(donor?.id===base.id){donor=null;choices.donor.clear();}
    stage=donor?'tracks':'donor';
   }else{donor=detail;choices.donor=new Set();stage='tracks';}
   $('mt-search').value='';limit=40;
  }catch(e){error(e.message);}finally{busy=false;$('mt-status').textContent='';if(open)show();}
 }
 async function loadLibrary(){
  if(loading)return;loading=true;error('');$('mt-status').textContent='Henter bibliotek …';
  try{const data=await api('/api/merge/library');items=data.items||[];$('mt-status').textContent=items.length+' filer'+(data.truncated?' · Listen er begrænset til 5.000 filer':'');if(stage!=='tracks')renderPicker();}
  catch(e){error(e.message);$('mt-status').textContent='Biblioteket kunne ikke indlæses.';}finally{loading=false;}
 }
 async function loadJobs(){
  if(jobsLoading)return;jobsLoading=true;
  try{
   const data=await api('/api/merge/jobs'),list=$('mt-jobs');list.replaceChildren();
   if(!data.jobs?.length)list.append(node('p','Ingen filer i flettekøen.','muted'));
   for(const job of data.jobs||[]){
    const row=node('div',null,'cw-job'),copy=node('div');copy.append(node('strong',job.name),node('p',({queued:'Venter',running:'Fletter',done:'Færdig',error:'Kræver kontrol',cancelled:'Annulleret'})[job.state]||job.state,'small'),node('p',job.detail,'muted small'));
    if(job.state==='running'){const progress=node('progress');progress.max=100;if(Number.isFinite(job.progress))progress.value=job.progress;progress.setAttribute('aria-label','Fletning af '+job.name);copy.append(progress);if(Number.isFinite(job.progress))copy.append(node('p',job.progress+' %','muted small'));}
    row.append(copy);
    const action=async kind=>{try{await post('jobs/'+job.id+'/'+kind);await loadJobs();}catch(e){error(e.message);}};
    if(['queued','error'].includes(job.state))row.append(button('Fjern fra kø',()=>action('cancel'),'quiet'));
    if(job.state==='error')row.append(button('Prøv igen',()=>action('retry')));
    list.append(row);
   }
  }catch(e){error(e.message);}finally{jobsLoading=false;}
 }
 $('mt-open').onclick=()=>{open=true;$('cw-cards').hidden=true;$('mt-panel').hidden=false;show();loadLibrary();loadJobs();};
 $('mt-back').onclick=()=>{if(busy)return;open=false;$('mt-panel').hidden=true;$('cw-cards').hidden=false;};
 $('mt-search').oninput=()=>{limit=40;renderPicker();};
 $('mt-refresh').onclick=()=>{if(!busy)loadLibrary();};$('mt-jobs-refresh').onclick=loadJobs;
 $('mt-form').onsubmit=async event=>{
  event.preventDefault();if(busy)return;error('');if(!choices.donor.size){error('Vælg mindst ét spor fra den anden fil.');return;}
  const offset=Number($('mt-offset').value);if(!Number.isInteger(offset)||Math.abs(offset)>3600000){error('Angiv tidsforskydningen i hele millisekunder.');return;}
  busy=true;show();
  try{
   const selection=(file,key)=>({id:file.id,fingerprint:file.fingerprint,tracks:[...choices[key]]});
   const result=await post('queue',{base:selection(base,'base'),donor:selection(donor,'donor'),offset_ms:offset});
   base=null;donor=null;choices.base.clear();choices.donor.clear();stage='base';$('mt-offset').value='0';$('mt-status').textContent='Tilføjet til køen · '+result.output;
   await loadJobs();
  }catch(e){error(e.message);}finally{busy=false;show();}
 };
 setInterval(()=>{if(open&&location.hash==='#conversion'&&!document.hidden)loadJobs();},3000);
})();
