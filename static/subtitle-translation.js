(() => {
 const $=id=>document.getElementById(id), node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e;};
 const button=(text,fn,cls='secondary')=>{const b=node('button',text,cls);b.type='button';b.onclick=fn;return b;};
 const post=(path,data={})=>api('/api/subtitles/'+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 const error=(id,text)=>{$(id).textContent=text||'';$(id).hidden=!text;};
 let items=[],languages={},auth={},selected=new Set(),details=new Map(),failed=new Map(),review=[],step=0,busy=false,limit=40,open=false,probing=false,generation=0,modelsFor=null,jobSignature='',loginRevision=null;
 const name=code=>languages[code]||code||'Ukendt sprog';
 const trackLabel=t=>[name(t.language),t.codec==='hdmv_pgs_subtitle'?'PGS · OCR':t.codec.toUpperCase(),t.kind==='sidecar'?'Separat fil':'I videofilen',t.forced?'Kun tvungne undertekster':'',t.label].filter(Boolean).join(' · ');
 const detail=file=>details.get(file.id)||file;
 const matching=()=>items.filter(f=>(f.title+' '+f.name).toLocaleLowerCase().includes($('st-search').value.toLocaleLowerCase())).sort((a,b)=>a.title.localeCompare(b.title,'da'));
 const visible=()=>matching().filter(f=>(detail(f).tracks||[]).length>0);
 function tracks(parent,rows){const list=node('div',null,'st-track-list');for(const t of rows)list.append(node('span',trackLabel(t),'st-track'));if(!rows.length)list.append(node('span','Ingen undertekster fundet','muted'));parent.append(list);}
 function selection(){ $('st-selection').hidden=!selected.size;$('st-count').textContent=selected.size+' film valgt';$('st-configure').disabled=busy||!selected.size; }
 function render(){
  const list=$('st-films');list.replaceChildren();const found=visible(),pending=matching().filter(f=>!detail(f).probed&&!failed.has(f.id)).length;
  $('st-status').textContent=found.length+' film med undertekster'+(pending?' · Undersøger biblioteket …':'')+(failed.size?' · '+failed.size+' filer kunne ikke undersøges':'');
  if(!found.length)list.append(node('p',pending?'Leder efter film med undertekster …':'Ingen film med undertekster fundet. Prøv en anden søgning eller opdater biblioteket.','muted'));
  for(const file of found.slice(0,limit)){
   const d=detail(file),row=node('article',null,'cw-film st-film'),check=node('input'),info=node('div',null,'cw-film-info');check.type='checkbox';check.checked=selected.has(file.id);check.disabled=busy||!d.eligible;check.setAttribute('aria-label','Vælg '+file.title);
   check.onchange=()=>{check.checked?selected.add(file.id):selected.delete(file.id);selection();};
   info.append(node('h3',file.title),node('p',file.name,'muted small'));tracks(info,d.tracks||[]);
   if(!d.eligible)info.append(node('p',d.reason,'muted'));
   if(!d.probed)info.append(node('p',failed.get(file.id)||'Læser indbyggede undertekster …','muted small'));
   const inspect=button(failed.has(file.id)?'Prøv igen':'Se undertekster',async()=>{try{failed.delete(file.id);await probe(file);render();}catch(e){error('st-error',e.message);}});inspect.disabled=busy;
   row.append(check,info,inspect);list.append(row);
  }
  if(found.length>limit)list.append(button('Vis flere film',()=>{limit+=40;render();probeVisible();}));selection();
 }
 async function probe(file){
  if(details.has(file.id))return details.get(file.id);
  const current=generation,data=await api('/api/subtitles/library/'+encodeURIComponent(file.id));
  if(current===generation){details.set(file.id,data);failed.delete(file.id);if(!data.tracks?.length)selected.delete(file.id);}return data;
 }
 async function probeVisible(){
  if(probing)return;probing=true;const current=generation;
  try{while(open&&current===generation){
   const file=matching().find(f=>!detail(f).probed&&!details.has(f.id)&&!failed.has(f.id));if(!file)break;
   try{await probe(file);}catch(e){if(current===generation)failed.set(file.id,e.message);}
   if(!$('st-dialog').open&&current===generation)render();
  }}finally{probing=false;if(current!==generation&&open)probeVisible();}
 }
 async function loadLibrary(){
  $('st-status').textContent='Henter film …';error('st-error','');const current=++generation;details.clear();failed.clear();
  try{const result=await api('/api/subtitles/library');if(current!==generation)return;items=result.items;selected=new Set([...selected].filter(id=>items.some(f=>f.id===id)));render();if(result.truncated)error('st-error','Biblioteket viser højst 5.000 film.');probeVisible();}
  catch(e){error('st-error',e.message);$('st-status').textContent='Biblioteket kunne ikke hentes.';}
 }
 async function loadModels(){
  const account=$('st-account').value;if(!auth.connected||!auth.enabled){modelsFor=null;$('st-model').replaceChildren(node('option','Forbind ChatGPT med planadgang først'));return;}
  if(modelsFor===account)return;
  $('st-model').replaceChildren(node('option','Henter modeller …'));
  try{const result=await api('/api/subtitles/models?account='+encodeURIComponent(account));if($('st-account').value!==account)return;
   $('st-model').replaceChildren();for(const m of result.models){const option=node('option',m.name);option.value=m.id;$('st-model').append(option);}modelsFor=account;
   if(!result.models.length)error('st-error','Kontoen har ingen tilgængelige modeller til oversættelse.');
  }catch(e){error('st-error',e.message);$('st-model').replaceChildren(node('option','Modeller kunne ikke hentes'));}
 }
 async function loadJobs(){
  try{const result=await api('/api/subtitles/jobs');languages=result.languages;auth=result.auth;
   const options=(auth.accounts||[]).map(a=>({value:a.id,label:a.email+' · '+a.id.slice(-6)}));
   if(JSON.stringify(options)!==$('st-account').dataset.options){$('st-account').replaceChildren();for(const a of options){const option=node('option',a.label);option.value=a.value;$('st-account').append(option);}$('st-account').dataset.options=JSON.stringify(options);}
   $('st-account').value=auth.active||'';
   $('st-auth-status').textContent=auth.connected?(auth.enabled?'ChatGPT er forbundet · klar til oversættelse':'Logget ind · tillad brug af ChatGPT-abonnementet for at oversætte'):'Forbind din ChatGPT-konto for at starte oversættelser.';
   $('st-disconnect').hidden=!auth.connected;
   renderLogin(auth.login);
   if(loginRevision!==null&&auth.connected&&auth.revision!==loginRevision){$('st-login-guide').hidden=true;loginRevision=null;modelsFor=null;}
   loadModels();const list=$('st-jobs');list.replaceChildren();
   if(!result.jobs.length)list.append(node('p','Ingen film i oversættelseskøen.','muted'));
   for(const job of result.jobs){
    const row=node('article',null,'st-job');row.append(node('strong',job.title),node('p',(job.targets||[]).map(name).join(', ')+' · '+({queued:'Venter',running:'Arbejder',done:'Færdig',error:'Kræver handling',cancelled:'Annulleret'})[job.state]),node('p',job.detail,'muted small'));
    const progress=node('progress');progress.max=100;progress.value=job.progress||0;progress.setAttribute('aria-label','Oversættelse af '+job.title);row.append(progress);
    const action=async kind=>{try{await post('jobs/'+job.job+'/'+kind);await loadJobs();}catch(e){error('st-error',e.message);}};
    if(job.state==='error')row.append(button('Genoptag',()=>action('retry')));
    if(['queued','running','error'].includes(job.state))row.append(button('Annuller',()=>action('cancel'),'quiet'));
    if(job.outputs?.length)row.append(node('p',job.outputs.join(' · '),'small'));list.append(row);
   }
   const signature=JSON.stringify(result.jobs.filter(j=>j.outputs?.length).map(j=>[j.job,j.outputs]));
   if(jobSignature&&signature!==jobSignature&&!$('st-dialog').open)loadLibrary();jobSignature=signature;
  }catch(e){error('st-error',e.message);}
 }
 function showStep(){
  const fields=$('st-fields');fields.replaceChildren();error('st-dialog-error','');$('st-prev').disabled=step===0;$('st-remove').hidden=step>=review.length;
  if(!review.length){$('st-dialog').close();selection();return;}
  if(step>=review.length){
   $('st-step').textContent='GENNEMSE DIT VALG';$('st-dialog-title').textContent='Klar til at oversætte '+review.length+' film';$('st-next').textContent='Start oversættelser';
   for(const r of review){const row=node('div',null,'st-review');row.append(node('strong',r.title),node('p',trackLabel(r.tracks.find(t=>t.id===r.source)),'muted small'),node('p','Nye sprog: '+r.targets.map(name).join(', ')));fields.append(row);}
   fields.append(node('p','Teksten sendes til OpenAI med den valgte konto og model. Resultatet gemmes som nye SRT-filer ved filmen med de oprindelige tidskoder. PGS kræver OCR og kan indeholde genkendelsesfejl.','muted'));return;
  }
  const r=review[step];$('st-step').textContent='FILM '+(step+1)+' AF '+review.length;$('st-dialog-title').textContent=r.title;$('st-next').textContent=step===review.length-1?'Gennemse kø →':'Næste film →';
  fields.append(node('h3','Eksisterende undertekster'));tracks(fields,r.tracks);
  const label=node('label','Kildespor'),select=node('select');for(const t of r.tracks.filter(t=>t.supported)){const opt=node('option',trackLabel(t));opt.value=t.id;opt.selected=t.id===r.source;select.append(opt);}select.onchange=()=>{r.source=select.value;showStep();};label.append(select);fields.append(label);
  const source=r.tracks.find(t=>t.id===r.source);fields.append(node('p',source?.forced?'Dette spor indeholder kun tvungne undertekster. Resultatet gemmes også som forced.':'Engelsk vælges automatisk, når et fuldt engelsk spor findes. Du kan vælge et andet kildespor.','muted small'));
  const dropdown=node('details',null,'st-languages'),summary=node('summary'),choices=node('div',null,'st-language-options');
  const update=()=>summary.textContent=r.targets.length?r.targets.map(name).join(', '):'Vælg målsprog (flere kan vælges)';update();
  const existing=new Set(r.tracks.map(t=>t.language));
  for(const [code,title] of Object.entries(languages)){
   const row=node('label'),check=node('input');check.type='checkbox';check.checked=r.targets.includes(code);check.disabled=existing.has(code);
   check.onchange=()=>{r.targets=check.checked?[...r.targets,code]:r.targets.filter(t=>t!==code);update();};row.append(check,node('span',title+(existing.has(code)?' · findes allerede':'')));choices.append(row);
  }
  dropdown.append(summary,choices);fields.append(dropdown,node('p','Eksisterende sprog er markeret og overskrives ikke. Nye undertekster gemmes som SRT, også når kilden er PGS.','muted small'));
 }
 $('st-configure').onclick=async()=>{
  if(busy)return;error('st-error','');if(!auth.connected||!auth.enabled||!modelsFor){error('st-error','Forbind ChatGPT, og vælg en tilgængelig model først.');return;}
  busy=true;selection();try{review=[];for(const file of items.filter(f=>selected.has(f.id))){const d=await probe(file);if(!d.eligible||!d.preferred)throw new Error(file.title+': '+(d.reason||'Ingen SRT/PGS eller andre understøttede tekstspor fundet.'));review.push({...d,source:d.preferred,targets:[]});}step=0;showStep();$('st-dialog').showModal();}
  catch(e){error('st-error',e.message);}finally{busy=false;selection();}
 };
 $('st-form').onsubmit=async event=>{event.preventDefault();if(busy)return;if(step<review.length){if(!review[step].targets.length){error('st-dialog-error','Vælg mindst ét nyt sprog.');return;}step++;showStep();return;}
  busy=true;$('st-next').disabled=true;try{await post('queue',{account:auth.active,model:$('st-model').value,items:review.map(r=>({id:r.id,snapshot:r.snapshot,source:r.source,targets:r.targets}))});$('st-dialog').close();selected.clear();render();await loadJobs();}
  catch(e){error('st-dialog-error',e.message);}finally{busy=false;$('st-next').disabled=false;render();}
 };
 $('st-prev').onclick=()=>{if(!busy&&step>0){step--;showStep();}};
 $('st-remove').onclick=()=>{if(!busy&&step<review.length){selected.delete(review[step].id);review.splice(step,1);showStep();selection();}};
 $('st-close').onclick=()=>{if(!busy)$('st-dialog').close();};$('st-dialog').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 let loginWindow=null,openedCode=null;
 function renderLogin(login){
  const active=login&&['starting','waiting'].includes(login.state);
  $('st-login').disabled=!!active;$('st-add-account').disabled=!!active;
  if(!login)return;
  $('st-login-guide').hidden=login.state==='completed'||login.state==='cancelled';
  $('st-device-details').hidden=login.state!=='waiting';
  $('st-login-cancel').hidden=!active;
  $('st-login-status').textContent=({starting:'Forbereder login …',waiting:'Afventer din godkendelse hos OpenAI',expired:'Koden er udløbet. Klik på Continue with ChatGPT for at prøve igen.',failed:login.error||'Login mislykkedes. Prøv igen.'})[login.state]||'';
  if(login.state==='waiting'){
   let url;try{url=new URL(login.verification_url);}catch{return;}
   if(url.origin!=='https://auth.openai.com'||url.username||url.password)return;
   $('st-login-code').textContent=login.user_code;$('st-login-link').href=url.href;
   if(loginWindow&&!loginWindow.closed&&openedCode!==login.user_code){loginWindow.location.href=url.href;openedCode=login.user_code;loginWindow=null;}
  }else{$('st-login-code').textContent='';$('st-login-link').removeAttribute('href');if(!active&&loginWindow&&!loginWindow.closed){loginWindow.close();loginWindow=null;}}
 }
 async function login(newAccount=false){
  loginWindow=window.open('about:blank','_blank');if(loginWindow)loginWindow.opener=null;
  try{loginRevision=auth.revision||0;const result=await post('auth/device',{account:newAccount?null:auth.active});renderLogin(result.login);}
  catch(e){if(loginWindow&&!loginWindow.closed)loginWindow.close();loginWindow=null;error('st-error',e.message);}
 }
 $('st-login').onclick=()=>login();$('st-add-account').onclick=()=>login(true);
 $('st-copy-code').onclick=async()=>{try{await navigator.clipboard.writeText($('st-login-code').textContent);$('st-copy-code').textContent='Kopieret';}catch{error('st-error','Markér og kopiér koden manuelt.');}};
 $('st-login-cancel').onclick=async()=>{try{await post('auth/cancel');if(loginWindow&&!loginWindow.closed)loginWindow.close();loginWindow=null;loginRevision=null;$('st-login-guide').hidden=true;$('st-login-code').textContent='';$('st-login-link').removeAttribute('href');await loadJobs();}catch(e){error('st-error',e.message);}};
 $('st-account').onchange=async()=>{try{await post('auth/select',{account:$('st-account').value});modelsFor=null;await loadJobs();}catch(e){error('st-error',e.message);}};
 $('st-disconnect').onclick=async()=>{try{const result=await post('auth/disconnect');modelsFor=null;await loadJobs();$('st-auth-status').textContent=result.message;}catch(e){error('st-error',e.message);}};
 $('st-open').onclick=async()=>{open=true;$('cw-cards').hidden=true;$('st-panel').hidden=false;await loadJobs();loadLibrary();};
 $('st-back').onclick=()=>{open=false;generation++;$('st-panel').hidden=true;$('cw-cards').hidden=false;};
 $('st-search').oninput=()=>{limit=40;render();probeVisible();};$('st-clear').onclick=()=>{selected.clear();render();};
 $('st-select-visible').onclick=()=>{for(const f of visible().slice(0,limit))if(detail(f).eligible)selected.add(f.id);render();};
 $('st-refresh').onclick=()=>{modelsFor=null;loadJobs();loadLibrary();};$('st-jobs-refresh').onclick=loadJobs;
 setInterval(()=>{if(open&&!document.hidden&&!$('st-dialog').open)loadJobs();},5000);
})();
