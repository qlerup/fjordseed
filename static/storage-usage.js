(() => {
 let requestId=0, hasData=false;
 const cards=[...document.querySelectorAll('[data-storage-usage]')];
 const field=(card,name)=>card.querySelector('[data-usage-'+name+']');
 const text=(element,value)=>{if(element.textContent!==value)element.textContent=value;};
 const units=['B','KiB','MiB','GiB','TiB'];
 const unitFor=(bytes,max)=>Math.min(max,Math.floor(Math.log2(Math.max(1,bytes))/10));
 const formatBytes=(bytes,unit)=>new Intl.NumberFormat('da-DK',{minimumFractionDigits:unit?2:0,maximumFractionDigits:unit?2:0}).format(bytes/1024**unit)+' '+units[unit];
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
 function releases(card,schedule,format){
  const summary=field(card,'release-summary'),list=field(card,'release-list');
  if(!schedule){text(summary,'Oprydningsoversigten kunne ikke hentes.');if(list.children.length)list.replaceChildren();delete list.dataset.snapshot;return;}
  text(summary,schedule.count===0?'Ingen midlertidige RSS-filer registreret på dette lager.':
   (schedule.scheduled_bytes>0?format(schedule.scheduled_bytes)+' forventes frigivet i alt. ':'')+
   schedule.count+' midlertidige downloads.'+(!schedule.available?' Afventer forbindelse til FjordSeed.':''));
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
   amount.textContent=(item.pending?'':'Ca. ')+format(item.bytes)+(item.pending?' afventer':' frigives');amount.className='storage-release-amount';
   row.append(label,amount);return row;
  }));
 }
 async function load(reset=false){
  if(!['#storage','#streaming'].includes(location.hash))return;
  const id=++requestId;
  if(reset)hasData=false;
  if(!hasData)for(const card of cards){
   field(card,'details').hidden=true;field(card,'percent').textContent='';field(card,'path').textContent='';
   field(card,'status').hidden=false;field(card,'status').textContent='Henter lagerplads…';
  }
  try{
   const data=await api('/api/storage/usage');if(id!==requestId)return;
   if(![data.total_bytes,data.used_bytes,data.free_bytes].every(n=>Number.isFinite(n)&&n>=0)||data.total_bytes===0)throw Error('Ingen lagertal');
   const percent=Math.min(100,Math.max(0,data.used_bytes/data.total_bytes*100));
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
   let totalMessage='Samlet midlertidigt forbrug kunne ikke måles.';
   try{
    const temporary=await api('/api/storage/temporary-usage');
    if(id!==requestId)return;
    const total=temporary.temporary_bytes;
    if(Number.isFinite(total)&&total>=0){
     totalMessage='Midlertidigt brugt i alt: '+formatBytes(total,unitFor(total,4))+' på tværs af downloadlagre, inkl. manuelle downloads.';
    }
    const bytes=temporary.current_temporary_bytes;
    if(temporary.path!==data.path||!Number.isFinite(bytes)||bytes<0)throw Error('Midlertidig plads ukendt');
    const width=Math.min(data.used_bytes,bytes)/data.total_bytes*100;
    for(const card of cards){
     const segment=field(card,'temporary-segment');
     for(const [key,value] of Object.entries({left:(percent-width)+'%',width:width+'%'}))if(segment.style[key]!==value)segment.style[key]=value;
     if(segment.hidden!==(width===0))segment.hidden=width===0;
     text(field(card,'temporary-label'),'Heraf midlertidigt forbrug på dette lager: '+format(bytes)+' · indgår i Brugt');
     text(field(card,'used-temporary'),'('+format(bytes)+' midlertidigt)');
     releases(card,temporary.current_rss_bytes===null?null:temporary.release_schedule,format);
    }
   }catch(e){
    if(id!==requestId)return;
    for(const card of cards){field(card,'temporary-segment').hidden=true;text(field(card,'temporary-label'),'Midlertidigt forbrug på dette lager kunne ikke måles.');text(field(card,'used-temporary'),'(midlertidig plads ukendt)');releases(card,null,format);}
   }
   for(const card of cards)text(field(card,'temporary-total'),totalMessage);
  }catch(e){
   if(id!==requestId)return;
   for(const card of cards){
    text(field(card,'status'),hasData?'Kunne ikke opdatere lagerplads. Viser senest hentede tal.':'Lagerplads kunne ikke hentes. Kontrollér forbindelsen og adgangen til lageret.');
    field(card,'status').hidden=false;
   }
  }
 }
 window.addEventListener('hashchange',()=>load());
 window.addEventListener('storage-changed',()=>load(true));
 setInterval(()=>{if(!document.hidden)load();},30000);
 load();
})();
