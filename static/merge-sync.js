(() => {
 const $=id=>document.getElementById(id),node=(tag,text)=>{const e=document.createElement(tag);if(text!=null)e.textContent=text;return e;};
 if(!$('ms-panel'))return;
 const post=data=>api('/api/merge/checks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
 let selection=null,key='',revision=0,task=null,polling=false,analysis=null,preview=null,explicit={base:false,donor:false};
 const offset=()=>Number($('mt-offset').value)||0;
 const clock=seconds=>{const n=Math.max(0,Math.round(seconds));return Math.floor(n/3600).toString().padStart(2,'0')+':'+Math.floor(n/60%60).toString().padStart(2,'0')+':'+(n%60).toString().padStart(2,'0');};
 const message=text=>{$('ms-error').textContent=text||'';$('ms-error').hidden=!text;};
 const elapsed=seconds=>{const value=Math.max(0,Math.round(seconds));return value>=60?Math.floor(value/60)+' min '+value%60+' sek':value+' sek';};
 function previewWork(data){
  $('ms-preview-work').hidden=false;const title=data.detail||'Klargør prøveklip';
  $('ms-preview-work-title').textContent=title+(data.stage_index?' · trin '+data.stage_index+' af '+data.stage_total:'');
  const bar=$('ms-preview-progress');bar.hidden=data.state==='error';if(Number.isFinite(data.progress))bar.value=data.progress;else bar.removeAttribute('value');
  const parts=[];
  if(data.state==='done')parts.push('Færdig');
  else if(Number.isFinite(data.progress))parts.push(new Intl.NumberFormat('da-DK',{maximumFractionDigits:1}).format(data.progress)+' % af dette trin');
  else if(data.stage==='video'||data.stage==='audio')parts.push('Afventer første fremdriftsmåling');
  if(Number.isFinite(data.processed_seconds)&&Number.isFinite(data.duration))parts.push(new Intl.NumberFormat('da-DK',{maximumFractionDigits:1}).format(data.processed_seconds)+' af '+new Intl.NumberFormat('da-DK',{maximumFractionDigits:1}).format(data.duration)+' sek. '+(data.stage==='audio'?'lyd':'video'));
  if(Number.isFinite(data.elapsed_seconds))parts.push('Forløbet: '+elapsed(data.elapsed_seconds));
  if(data.stale)parts.push('Afventer ny måling fra FFmpeg');
  else if(Number.isFinite(data.eta_seconds))parts.push('Ca. '+elapsed(data.eta_seconds)+' tilbage i dette trin');
  else if(data.state==='running'&&['video','audio'].includes(data.stage)&&data.progress!==100)parts.push('Resterende tid beregnes …');
  $('ms-preview-stats').textContent=parts.join(' · ');$('ms-top-stats').textContent=parts.join(' · ');$('ms-top-stats').hidden=false;
  if(task?.kind==='preview')$('ms-preview').textContent='Laver prøve'+(Number.isFinite(data.progress)?' · '+new Intl.NumberFormat('da-DK',{maximumFractionDigits:0}).format(data.progress)+' %':' …');
 }
 const trackLabel=t=>[t.language,t.codec,t.profile,t.channels?t.channels+' kanaler':'',t.title].filter(Boolean).join(' · ');
 function stop(){for(const id of ['ms-base-video','ms-audio-player'])$(id).pause();}
 function clearPlayer(){stop();preview=null;$('ms-player').hidden=true;for(const id of ['ms-base-video','ms-audio-player']){$(id).removeAttribute('src');$(id).load();}}
 function controls(){const hasAudio=['base','donor'].every(k=>$("ms-"+k+"-audio").value!=='');const imported=selection?.choices.donor.includes(Number($('ms-donor-audio').value))&&$('ms-donor-audio').value!=='';$('ms-analyse').disabled=!!task||!hasAudio||!selection?.base||!selection?.donor;$('ms-preview').disabled=!!task||!selection?.base||!selection?.donor||!imported;$('ms-preview-hint').hidden=!!imported;$('ms-length').disabled=task?.kind==='preview';$('ms-start').disabled=task?.kind==='preview';if(!task)$('ms-preview').textContent='Lav '+($('ms-length').value||'…')+' sek. prøveklip';}
 function setOffset(value,center=false){value=Math.max(-3600000,Math.min(3600000,Math.round(value)));$('mt-offset').value=value;if(center){$('ms-slider').min=value-1000;$('ms-slider').max=value+1000;}$('mt-offset').dispatchEvent(new Event('input',{bubbles:true}));}
 function updateOffset(){const value=offset();$('ms-current').textContent='Aktuel forskydning: '+(value>0?'+':'')+value+' ms';if(value<Number($('ms-slider').min)||value>Number($('ms-slider').max)){$('ms-slider').min=value-1000;$('ms-slider').max=value+1000;}$('ms-slider').value=value;draw();synchronise(true);}
 function fillAudio(kind,file){
  const select=$('ms-'+kind+'-audio'),before=select.value;let tracks=file.tracks.filter(t=>t.kind==='audio');
  const imported=tracks.filter(t=>selection.choices[kind].includes(t.id));if(kind==='donor'&&imported.length)tracks=imported;select.replaceChildren();
  if(!tracks.length){const option=node('option','Ingen lyd i filen');option.value='';select.append(option);}
  for(const t of tracks){const option=node('option',trackLabel(t));option.value=t.id;select.append(option);}
  const selected=tracks.find(t=>selection.choices[kind].includes(t.id));
  if(explicit[kind]&&tracks.some(t=>String(t.id)===before))select.value=before;
  else select.value=String((selected||tracks[0])?.id??'');
 }
 window.addEventListener('fjord-merge-selection',event=>{
  selection=event.detail;if(selection.active===false)stop();const next=selection.stage==='tracks'?[selection.base?.id,...(selection.base?.fingerprint||[]),selection.donor?.id,...(selection.donor?.fingerprint||[])].join(':'):'';
  const changed=next!==key;
  if(changed){key=next;revision++;task=null;analysis=null;explicit={base:false,donor:false};clearPlayer();$('ms-analysis').hidden=true;$('ms-status').textContent='';$('ms-progress').hidden=true;$('ms-preview-work').hidden=true;$('ms-top-stats').hidden=true;message('');}
  if(next){const before=[$('ms-base-audio').value,$('ms-donor-audio').value].join(':');fillAudio('base',selection.base);fillAudio('donor',selection.donor);const after=[$('ms-base-audio').value,$('ms-donor-audio').value].join(':');
   if(before!==after&&(analysis||preview||task)){revision++;task=null;analysis=null;$('ms-analysis').hidden=true;clearPlayer();$('ms-status').textContent='Lydspor ændret. Start en ny kontrol.';$('ms-progress').hidden=true;$('ms-preview-work').hidden=true;$('ms-top-stats').hidden=true;}
   if(changed)$('ms-start').value=Math.floor(Math.min(60,Math.max(0,selection.base.duration-16)));}
  controls();updateOffset();
 });
 for(const kind of ['base','donor'])$('ms-'+kind+'-audio').onchange=()=>{explicit[kind]=true;revision++;task=null;analysis=null;$('ms-analysis').hidden=true;clearPlayer();$('ms-status').textContent='Lydspor ændret. Start en ny kontrol.';$('ms-progress').hidden=true;$('ms-preview-work').hidden=true;$('ms-top-stats').hidden=true;controls();};
 function request(kind){
  const choice=(file,k)=>({id:file.id,fingerprint:file.fingerprint,tracks:selection.choices[k]});
  return {kind,base:choice(selection.base,'base'),donor:choice(selection.donor,'donor'),base_audio:$('ms-base-audio').value===''?null:Number($('ms-base-audio').value),donor_audio:$('ms-donor-audio').value===''?null:Number($('ms-donor-audio').value),offset_ms:offset(),start:Number($('ms-start').value),length:Number($('ms-length').value)};
 }
 async function begin(kind){
  if(task||!selection?.base||!selection?.donor)return;message('');stop();const generation=revision;
  if(kind==='preview'&&(!Number.isInteger(Number($('ms-length').value))||Number($('ms-length').value)<5||Number($('ms-length').value)>120)){message('Vælg en prøvelængde på 5 til 120 hele sekunder.');return;}
  if(kind==='analyse'){analysis=null;$('ms-analysis').hidden=true;}
  task={id:null,generation,kind};controls();$('ms-status').textContent=kind==='analyse'?'Leder efter de samme lyde …':'Klargør prøveklip …';$('ms-progress').hidden=false;$('ms-progress').removeAttribute('value');
  if(kind==='preview')previewWork({state:'queued',detail:'Venter på at lave prøveklippet',elapsed_seconds:0});else{$('ms-preview-work').hidden=true;$('ms-top-stats').hidden=true;}
  try{const data=await post(request(kind));if(generation!==revision)return;task.id=data.id;await poll();}
  catch(e){if(generation===revision){task=null;message(e.message);if(kind==='preview')previewWork({state:'error',detail:e.message});$('ms-progress').hidden=true;controls();}}
 }
 async function poll(){
  if(polling||!task?.id)return;polling=true;const current=task;
  try{
   const data=await api('/api/merge/checks/'+current.id);if(task!==current||current.generation!==revision)return;
   $('ms-status').textContent=data.detail||'';if(Number.isFinite(data.progress))$('ms-progress').value=data.progress;
   else $('ms-progress').removeAttribute('value');
   if(current.kind==='preview')previewWork(data);
   if(data.state==='error'){task=null;message(data.detail);$('ms-progress').hidden=true;controls();}
   else if(data.state==='done'){task=null;$('ms-progress').hidden=true;controls();if(data.result.kind==='analyse')renderAnalysis(data.result);else renderPreview(data.result,current.id);}
  }catch(e){if(task===current){task=null;message(e.message);if(current.kind==='preview')previewWork({state:'error',detail:e.message});$('ms-progress').hidden=true;controls();}}finally{polling=false;}
 }
 function renderAnalysis(result){
  analysis=result;$('ms-analysis').hidden=false;$('ms-verdict').textContent=result.reliable?'Match fundet: '+(result.offset_ms>0?'+':'')+result.offset_ms+' ms':result.status==='drift'?'Timingen ændrer sig gennem filmen':'Intet sikkert match';$('ms-explanation').textContent=result.detail;
  $('ms-waveform').hidden=!result.waveform;
  const table=node('table'),head=node('tr');for(const text of ['Sted i hovedfilen','Forskydning','Matchscore'])head.append(node('th',text));const thead=node('thead');thead.append(head);table.append(thead);const body=node('tbody');
  for(const sample of result.samples){const row=node('tr');row.append(node('td',clock(sample.time)),node('td',sample.offset_ms==null?'—':sample.offset_ms+' ms'),node('td',sample.trusted?Number(sample.score).toFixed(2):'Usikkert'));body.append(row);}table.append(body);$('ms-measurements').replaceChildren(table);
  $('ms-apply').hidden=!result.reliable;$('ms-apply').textContent='Brug '+(result.offset_ms>0?'+':'')+result.offset_ms+' ms';
  if(result.waveform)$('ms-start').value=Math.floor(result.waveform.base_start);
  draw();
 }
 function draw(){
  const canvas=$('ms-waveform'),wave=analysis?.waveform;if(!wave||$('ms-analysis').hidden)return;
  const width=canvas.clientWidth||600,height=180,ratio=window.devicePixelRatio||1;canvas.width=Math.round(width*ratio);canvas.height=height*ratio;const context=canvas.getContext('2d');context.scale(ratio,ratio);context.clearRect(0,0,width,height);
  context.strokeStyle='#344450';context.beginPath();context.moveTo(0,height/2);context.lineTo(width,height/2);context.stroke();
  function plot(values,color,donor){context.beginPath();for(let x=0;x<=width;x++){const index=Math.floor(x/width*wave.base.length),time=wave.base_start+index/wave.rate;const at=donor?Math.round((time-offset()/1000-wave.donor_start)*wave.rate):index;const level=values[at]||0;context.lineTo(x,height/2-level*70);}for(let x=width;x>=0;x--){const index=Math.floor(x/width*wave.base.length),time=wave.base_start+index/wave.rate;const at=donor?Math.round((time-offset()/1000-wave.donor_start)*wave.rate):index;context.lineTo(x,height/2+(values[at]||0)*70);}context.closePath();context.globalAlpha=.25;context.fillStyle=color;context.fill();context.globalAlpha=.9;context.strokeStyle=color;context.lineWidth=1;context.stroke();context.globalAlpha=1;}
  plot(wave.base,'#64d7b5',false);plot(wave.donor,'#d9aa62',true);
  context.fillStyle='#b9c8cf';context.font='11px sans-serif';context.fillText(clock(wave.base_start),8,height-8);context.fillText(clock(wave.base_start+wave.base.length/wave.rate),Math.max(8,width-65),height-8);
 }
 function renderPreview(result,id){
  clearPlayer();preview=result;$('ms-player').hidden=false;$('ms-base-video').src='/api/merge/checks/'+id+'/base.mp4';$('ms-audio-player').src='/api/merge/checks/'+id+'/donor.m4a';
  const chosen=selection.donor.tracks.find(t=>t.id===Number($('ms-donor-audio').value));$('ms-playing-track').textContent='Hovedfilens video + nyt lydspor: '+(chosen?trackLabel(chosen):'valgt lydspor');
  $('ms-seek').max=result.base_duration;$('ms-seek').value=0;synchronise(true);
 }
 function playerControls(){if(!preview)return;const base=$('ms-base-video'),audio=$('ms-audio-player'),ready=base.readyState>=2&&audio.readyState>=2;$('ms-play').disabled=!ready;$('ms-play').textContent=base.ended?'Afspil igen':base.paused?'Afspil med nyt lydspor':'Pause';$('ms-seek').value=Math.min(base.currentTime,preview.base_duration);$('ms-clip-time').textContent=clock(base.currentTime).slice(3)+' / '+clock(preview.base_duration).slice(3);}
 function synchronise(force=false){
  if(!preview)return;const base=$('ms-base-video'),donor=$('ms-audio-player'),time=preview.base_start+base.currentTime-offset()/1000-preview.donor_start;
  const inRange=time>=0&&time<preview.donor_duration;
  base.muted=true;donor.muted=!inRange;
  $('ms-player-status').textContent=inRange?'Tid i filmen: '+clock(preview.base_start+base.currentTime)+' · nyt lydspor '+(offset()===0?'uden forskydning':offset()>0?offset()+' ms senere':Math.abs(offset())+' ms tidligere'):'Forskydningen ligger uden for prøveklippet. Vælg et andet tidspunkt eller lav et nyt prøveklip.';
  playerControls();
  if(!inRange){donor.pause();return;}
  if(donor.readyState>=1&&!donor.seeking&&Math.abs(donor.currentTime-time)>(force?.005:.08)){try{donor.currentTime=time;}catch{}}
  donor.playbackRate=base.playbackRate;
  if(base.paused){donor.pause();return;}
  if(donor.paused&&donor.readyState>=2)donor.play().catch(()=>{$('ms-player-status').textContent='Tryk på Afspil med nyt lydspor for at starte prøven.';});
 }
 $('ms-base-video').addEventListener('play',()=>synchronise(true));for(const event of ['pause','ended'])$('ms-base-video').addEventListener(event,()=>{$('ms-audio-player').pause();playerControls();});
 for(const event of ['timeupdate','seeking','seeked','ratechange','loadedmetadata'])$('ms-base-video').addEventListener(event,()=>synchronise(event!=='timeupdate'));
 $('ms-base-video').addEventListener('canplay',playerControls);
 $('ms-audio-player').addEventListener('loadedmetadata',()=>synchronise(true));$('ms-audio-player').addEventListener('canplay',()=>synchronise());$('ms-audio-player').addEventListener('seeked',()=>synchronise());
 $('ms-play').onclick=()=>{const base=$('ms-base-video');if(!base.paused){stop();return;}if(base.ended)base.currentTime=0;synchronise(true);base.play().catch(()=>message('Prøveklippet kunne ikke afspilles. Lav et nyt klip.'));};
 $('ms-replay').onclick=()=>{stop();$('ms-base-video').currentTime=0;synchronise(true);};
 function stepFrame(direction){if(!preview)return;stop();const base=$('ms-base-video'),fps=preview.video_fps||25;base.currentTime=Math.max(0,Math.min(preview.base_duration-1/fps,base.currentTime+direction/fps));synchronise(true);}
 $('ms-frame-back').onclick=()=>stepFrame(-1);$('ms-frame-next').onclick=()=>stepFrame(1);
 $('ms-seek').oninput=()=>{if(!preview)return;$('ms-base-video').currentTime=Number($('ms-seek').value);synchronise(true);};
 $('ms-length').oninput=()=>{$('ms-preview').textContent='Lav '+($('ms-length').value||'…')+' sek. prøveklip';};
 $('ms-fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await $('ms-stage').requestFullscreen();}catch{message('Fuld skærm kunne ikke åbnes i denne browser.');}};
 $('ms-analyse').onclick=()=>begin('analyse');$('ms-preview').onclick=()=>begin('preview');$('ms-apply').onclick=()=>{if(analysis?.reliable)setOffset(analysis.offset_ms,true);};
 $('mt-offset').addEventListener('input',updateOffset);$('ms-slider').oninput=()=>setOffset(Number($('ms-slider').value));
 document.querySelectorAll('#ms-nudges [data-ms]').forEach(b=>b.onclick=()=>setOffset(offset()+Number(b.dataset.ms)));
 document.querySelectorAll('.ms-shortcuts [data-position]').forEach(b=>b.onclick=()=>{if(selection?.base)$('ms-start').value=Math.floor(Math.max(0,selection.base.duration*Number(b.dataset.position)-7));});
 window.addEventListener('resize',draw);window.addEventListener('hashchange',()=>{if(location.hash!=='#conversion')stop();});
 document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});
 new MutationObserver(()=>{if($('mt-panel').hidden)stop();}).observe($('mt-panel'),{attributes:true,attributeFilter:['hidden']});
 $('mt-dialog').addEventListener('close',stop);
 setInterval(()=>{if(task&&!document.hidden)poll();},1000);setInterval(()=>{if(preview&&!$('ms-base-video').paused)synchronise();},100);
 updateOffset();controls();
})();
