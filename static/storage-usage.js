(() => {
 let requestId=0, hasData=false;
 const cards=[...document.querySelectorAll('[data-storage-usage]')];
 const field=(card,name)=>card.querySelector('[data-usage-'+name+']');
 const text=(element,value)=>{if(element.textContent!==value)element.textContent=value;};
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
     text(field(card,'used-temporary'),'Heraf midlertidige RSS-filer: '+format(bytes));
    }
   }catch(e){
    if(id!==requestId)return;
    for(const card of cards){field(card,'temporary-segment').hidden=true;text(field(card,'temporary-label'),'Midlertidig RSS-plads kunne ikke måles.');text(field(card,'used-temporary'),'Midlertidig RSS-plads kunne ikke måles.');}
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
