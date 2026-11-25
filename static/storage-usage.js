(() => {
 let requestId=0, hasData=false;
 const cards=[...document.querySelectorAll('[data-storage-usage]')];
 const field=(card,name)=>card.querySelector('[data-usage-'+name+']');
 const text=(element,value)=>{if(element.textContent!==value)element.textContent=value;};
 const units=['B','KiB','MiB','GiB','TiB'];
 const unitFor=(bytes,max)=>Math.min(max,Math.floor(Math.log2(Math.max(1,bytes))/10));
 const formatBytes=(bytes,unit)=>new Intl.NumberFormat('da-DK',{minimumFractionDigits:unit?2:0,maximumFractionDigits:unit?2:0}).format(bytes/1024**unit)+' '+units[unit];
 const formatAmount=bytes=>formatBytes(bytes,unitFor(bytes,4));
 const percentUsed=data=>Math.min(100,data.used_bytes/data.total_bytes*100);
 const hide=(element,hidden)=>{if(element.hidden!==hidden)element.hidden=hidden;};
 function segment(element,data,temporaryBytes){
  const width=Math.min(data.used_bytes,temporaryBytes)/data.total_bytes*100;
  const left=+((percentUsed(data)-width).toFixed(5))+'%',size=+(width.toFixed(5))+'%';
  if(element.style.left!==left)element.style.left=left;
  if(element.style.width!==size)element.style.width=size;
  hide(element,width===0);
 }
 function bufferBars(card,capacity,temporary){
  const buffer=temporary?.buffer_usage;
  const valid=buffer&&typeof buffer.path==='string'&&buffer.total_bytes>0&&
   [buffer.total_bytes,buffer.used_bytes,buffer.temporary_bytes].every(n=>Number.isFinite(n)&&n>=0);
  const shared=valid&&capacity&&capacity.path===temporary.path&&buffer.on_selected_filesystem;
  const selectedSegment=field(card,'temporary-segment'),selectedLabel=field(card,'temporary-label');
  if(shared){
   segment(selectedSegment,capacity,buffer.temporary_bytes);
   text(selectedLabel,'Heraf '+formatAmount(buffer.temporary_bytes)+' midlertidigt brugt');
   hide(selectedLabel,selectedSegment.hidden);
  }else{
   hide(selectedSegment,true);
   hide(selectedLabel,true);
  }
  hide(field(card,'buffer'),!valid||!!shared);
  if(!valid||shared)return;
  const bar=field(card,'buffer-bar'),percent=percentUsed(buffer);
  if(bar.value!==percent)bar.value=percent;
  segment(field(card,'buffer-segment'),buffer,buffer.temporary_bytes);
  text(field(card,'buffer-path'),buffer.path);
  text(field(card,'buffer-label'),'Heraf '+formatAmount(buffer.temporary_bytes)+' midlertidigt brugt · '+
   formatAmount(buffer.used_bytes)+' brugt af '+formatAmount(buffer.total_bytes));
 }
 function releaseBuckets(points){
  if(!points.length)return [];
  const steps=[1,2,3,6,12,24,48,168,720];
  function range(at,hours){
   const start=new Date(at*1000);start.setMinutes(0,0,0);
   if(hours<=24)start.setHours(Math.floor(start.getHours()/hours)*hours);
   else{
    const day=Math.floor(Date.UTC(start.getFullYear(),start.getMonth(),start.getDate())/86400000);
    const anchor=new Date(Math.floor(day/(hours/24))*(hours/24)*86400000);
    start.setFullYear(anchor.getUTCFullYear(),anchor.getUTCMonth(),anchor.getUTCDate());start.setHours(0);
   }
   const end=new Date(start);
   if(hours<24)end.setHours(end.getHours()+hours);else end.setDate(end.getDate()+hours/24);
   return {start,end};
  }
  // Count occupied windows so a distant release does not hide nearby detail.
  const step=steps.find(hours=>new Set(points.map(point=>range(point.at,hours).start.getTime())).size<=24)
   ||Math.ceil((Math.max(...points.map(p=>p.at))-Math.min(...points.map(p=>p.at)))/(24*86400))*24;
  const buckets=new Map();
  for(const point of points){const {start,end}=range(point.at,step),key=start.getTime();
   if(!buckets.has(key))buckets.set(key,{start,end,bytes:0});
   buckets.get(key).bytes+=point.bytes;
  }
  return [...buckets.values()].sort((a,b)=>a.start-b.start);
 }
 function releases(card,schedule){
  const summary=field(card,'release-summary'),list=field(card,'release-list');
  if(!schedule){text(summary,'Oprydningsoversigten kunne ikke hentes.');if(list.children.length)list.replaceChildren();delete list.dataset.snapshot;return;}
  text(summary,!schedule.available?'Afventer forbindelse til torrentklienten.':
   schedule.count===0?'Ingen downloads med automatisk filsletning.':
   (schedule.scheduled_bytes>0?'Ca. '+formatAmount(schedule.scheduled_bytes)+' forventes frigivet i alt. ':'')+
   schedule.count+' downloads med automatisk filsletning.'+
   (schedule.estimated_sizes?' For nogle downloads er pladsen anslået ud fra den hentede datamængde.':''));
  const date=d=>new Intl.DateTimeFormat('da-DK',{day:'numeric',month:'short'}).format(d);
  const hour=d=>String(d.getHours()).padStart(2,'0');
  const rows=releaseBuckets(schedule.timeline||[]).map(b=>{
   const sameDay=b.start.toDateString()===new Date(b.end-1).toDateString();
   const midnight=b.end.getHours()===0;
   return {label:sameDay?date(b.start)+' kl. '+hour(b.start)+'–'+(midnight?'24':hour(b.end)):
    date(b.start)+' – '+date(new Date(b.end-1)),bytes:b.bytes};
  });
  if(schedule.soon_bytes>0)rows.unshift({label:'Ved næste oprydning',bytes:schedule.soon_bytes});
  if(schedule.unplaced_bytes>0)rows.push({label:'Tidspunkt afventer',bytes:schedule.unplaced_bytes,pending:true});
  const signature=JSON.stringify(rows);
  if(list.dataset.snapshot===signature)return;
  list.dataset.snapshot=signature;
  list.replaceChildren(...rows.map(item=>{
   const row=document.createElement('li'),label=document.createElement('strong'),amount=document.createElement('span');
   label.textContent=item.label;label.className='storage-release-name';
   amount.textContent=(item.pending?'':'Ca. ')+formatAmount(item.bytes)+(item.pending?' afventer':' frigives');amount.className='storage-release-amount';
   row.append(label,amount);return row;
  }));
 }
 async function loadTemporary(id){
  let temporary;
  try{
   temporary=await api('/api/storage/temporary-usage');
  }catch(e){temporary=null;}
  if(id!==requestId)return;
  const total=temporary?.temporary_bytes;
  const totalMessage=Number.isFinite(total)&&total>=0?'Midlertidige downloadmapper bruger '+formatAmount(total)+' i alt.':
   'Samlet midlertidigt forbrug kunne ikke måles.';
  for(const card of cards){
   text(field(card,'temporary-total'),totalMessage);
   releases(card,temporary?.release_schedule);
  }
  return temporary;
 }
 async function loadCapacity(id,reset){
  if(reset)hasData=false;
  if(!hasData)for(const card of cards){
   field(card,'details').hidden=true;field(card,'percent').textContent='';field(card,'path').textContent='';
   field(card,'status').hidden=false;field(card,'status').textContent='Henter lagerplads…';
  }
  try{
   const data=await api('/api/storage/usage');if(id!==requestId)return;
   if(![data.total_bytes,data.used_bytes,data.free_bytes].every(n=>Number.isFinite(n)&&n>=0)||data.total_bytes===0)throw Error('Ingen lagertal');
   const percent=percentUsed(data);
   const reserved=Math.max(0,data.total_bytes-data.used_bytes-data.free_bytes);
   // Use the same binary unit for every figure, with explicit IEC labels.
   const unit=unitFor(data.total_bytes,3);
   const format=n=>formatBytes(n,unit);
   for(const card of cards){
    text(field(card,'path'),data.path);
    text(field(card,'percent'),new Intl.NumberFormat('da-DK',{maximumFractionDigits:1}).format(percent)+' % brugt');
    if(field(card,'bar').value!==percent)field(card,'bar').value=percent;
    const level=percent>=95?'critical':percent>=85?'warning':'normal';
    if(card.dataset.level!==level)card.dataset.level=level;
    for(const key of ['used','free','total'])text(field(card,key),format(data[key+'_bytes']));
    const note=field(card,'reserved-note');
    text(note,reserved>0?'Systemreserveret: '+format(reserved)+' — indgår i totalen, men er ikke tilgængelig til downloads.':'');
    if(note.hidden!==(reserved===0))note.hidden=reserved===0;
    if(!field(card,'status').hidden)field(card,'status').hidden=true;
    if(field(card,'details').hidden)field(card,'details').hidden=false;
   }
   hasData=true;
   return data;
  }catch(e){
   if(id!==requestId)return;
   for(const card of cards){
    text(field(card,'status'),hasData?'Kunne ikke opdatere lagerplads. Viser senest hentede tal.':'Lagerplads kunne ikke hentes. Kontrollér forbindelsen og adgangen til lageret.');
    field(card,'status').hidden=false;
   }
  }
 }
 async function load(reset=false){
  if(!['#storage','#streaming'].includes(location.hash))return;
  const id=++requestId;
  const [capacity,temporary]=await Promise.all([loadCapacity(id,reset),loadTemporary(id)]);
  if(id===requestId)for(const card of cards)bufferBars(card,capacity,temporary);
 }
 window.addEventListener('hashchange',()=>load());
 window.addEventListener('storage-changed',()=>load(true));
 setInterval(()=>{if(!document.hidden)load();},30000);
 load();
})();
