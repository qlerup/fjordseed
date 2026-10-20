(() => {
 let requestId=0;
 const cards=[...document.querySelectorAll('[data-storage-usage]')];
 const field=(card,name)=>card.querySelector('[data-usage-'+name+']');
 async function load(){
  if(!['#storage','#streaming'].includes(location.hash))return;
  const id=++requestId;
  for(const card of cards){
   field(card,'details').hidden=true;field(card,'percent').textContent='';field(card,'path').textContent='';
   field(card,'status').hidden=false;field(card,'status').textContent='Henter lagerplads…';
  }
  try{
   const data=await api('/api/storage/usage');if(id!==requestId)return;
   if(![data.total_bytes,data.used_bytes,data.free_bytes].every(n=>Number.isFinite(n)&&n>=0)||data.total_bytes===0)throw Error('Ingen lagertal');
   const percent=Math.min(100,Math.max(0,data.used_bytes/data.total_bytes*100));
   for(const card of cards){
    field(card,'path').textContent=data.path;
    field(card,'percent').textContent=new Intl.NumberFormat('da-DK',{maximumFractionDigits:1}).format(percent)+' % brugt';
    field(card,'bar').value=percent;
    card.dataset.level=percent>=95?'critical':percent>=85?'warning':'normal';
    for(const key of ['used','free','total'])field(card,key).textContent=size(data[key+'_bytes']);
    field(card,'status').hidden=true;field(card,'details').hidden=false;
   }
  }catch(e){
   if(id!==requestId)return;
   for(const card of cards)field(card,'status').textContent='Lagerplads kunne ikke hentes. Kontrollér forbindelsen og adgangen til lageret.';
  }
 }
 window.addEventListener('hashchange',load);
 window.addEventListener('storage-changed',load);
 setInterval(()=>{if(!document.hidden)load();},30000);
 load();
})();
