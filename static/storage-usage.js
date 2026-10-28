(() => {
 let requestId=0, hasData=false;
 const cards=[...document.querySelectorAll('[data-storage-usage]')];
 const field=(card,name)=>card.querySelector('[data-usage-'+name+']');
 const text=(element,value)=>{if(element.textContent!==value)element.textContent=value;};
 function releaseBuckets(points){
  if(!points.length)return [];
  const steps=[3,6,12,24,48,168,720];
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
  let step=steps.find(hours=>{
   const first=range(Math.min(...points.map(p=>p.at)),hours).start;
   const last=range(Math.max(...points.map(p=>p.at)),hours).end;
   return (last-first)/(hours*3600000)<=6.1;
  })||Math.ceil((Math.max(...points.map(p=>p.at))-Math.min(...points.map(p=>p.at)))/(6*86400))*24;
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
   const units=['B','KiB','MiB','GiB'];
   const unit=Math.min(3,Math.max(0,Math.floor(Math.log(data.total_bytes)/Math.log(1024))));
   const format=n=>new Intl.NumberFormat('da-DK',{minimumFractionDigits:unit?2:0,maximumFractionDigits:unit?2:0}).format(n/1024**unit)+' '+units[unit];
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
   try{
    const temporary=await api('/api/storage/temporary-usage');
    if(id!==requestId)return;
    if(temporary.path!==data.path||!Number.isFinite(temporary.current_rss_bytes)||temporary.current_rss_bytes<0)throw Error('RSS-plads ukendt');
    const bytes=Math.min(data.used_bytes,temporary.current_rss_bytes),width=bytes/data.total_bytes*100;
    for(const card of cards){
     const segment=field(card,'temporary-segment');
     for(const [key,value] of Object.entries({left:(percent-width)+'%',width:width+'%'}))if(segment.style[key]!==value)segment.style[key]=value;
     if(segment.hidden!==(bytes===0))segment.hidden=bytes===0;
     text(field(card,'temporary-label'),'Heraf midlertidige RSS-filer: '+format(bytes)+' · indgår i Brugt');
     text(field(card,'used-temporary'),'('+format(bytes)+' midlertidigt)');
     releases(card,temporary.release_schedule,format);
    }
   }catch(e){
    if(id!==requestId)return;
    for(const card of cards){field(card,'temporary-segment').hidden=true;text(field(card,'temporary-label'),'Midlertidig RSS-plads kunne ikke måles.');text(field(card,'used-temporary'),'(midlertidig plads ukendt)');releases(card,null,format);}
   }
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
