(() => {
 let requestId=0, hasData=false;
 const cards=[...document.querySelectorAll('[data-storage-usage]')];
 const field=(card,name)=>card.querySelector('[data-usage-'+name+']');
 const text=(element,value)=>{if(element.textContent!==value)element.textContent=value;};
 function releases(card,schedule,format){
  const summary=field(card,'release-summary'),list=field(card,'release-list');
  if(!schedule){text(summary,'Oprydningsoversigten kunne ikke hentes.');if(list.children.length)list.replaceChildren();delete list.dataset.snapshot;return;}
  const items=schedule.items||[];
  text(summary,schedule.count===0?'Ingen midlertidige RSS-filer registreret på dette lager.':
   (schedule.scheduled_bytes>0?format(schedule.scheduled_bytes)+' kan frigives ved de beregnede seedingmål. ':'')+
   (schedule.count>items.length?'Viser de næste '+items.length+' af '+schedule.count+' downloads.':schedule.count+' midlertidige downloads.')+
   (!schedule.available?' Afventer forbindelse til FjordSeed.':''));
  const signature=JSON.stringify(items);
  if(list.dataset.snapshot===signature)return;
  list.dataset.snapshot=signature;
  list.replaceChildren(...items.map(item=>{
   const row=document.createElement('li'),title=document.createElement('strong'),amount=document.createElement('span'),when=document.createElement('span'),note=document.createElement('p');
   title.textContent=item.name;title.className='storage-release-name';title.title=item.name;
   amount.textContent=format(item.reclaimable_bytes)+' frigives';amount.className='storage-release-amount';
   when.textContent=item.release_at?new Intl.DateTimeFormat('da-DK',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}).format(new Date(item.release_at*1000)):'Tidspunkt afventer';
   if(item.state==='soon')when.textContent='Ved næste oprydning';
   if(item.state==='retained')when.textContent='Beholdes';
   when.className='storage-release-time';note.className='small muted';note.textContent=item.message;
   if(item.bytes!==item.reclaimable_bytes)note.textContent+=' Fylder '+format(item.bytes)+'; delte filer eller filer, der beholdes, tælles ikke som frigivet plads.';
   row.append(title,amount,when,note);return row;
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
