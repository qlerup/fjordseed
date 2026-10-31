import {torrentLink, permissionOrigin, selectSeedTab, readTorrent, stageTorrent, MAX_AGE, TRACKER_ORIGINS} from './common.mjs';

export function createPackageDelivery({destination, status}) {
  let chain=Promise.resolve(),processing=false,rerun=false;
  const loginShown=new Set();
  const mutate=fn=>{const next=chain.then(fn);chain=next.catch(()=>{});return next;};
  const read=async()=> (await chrome.storage.session.get('packagePending')).packagePending||[];
  async function note(message,error=false){
    await status(message,error);
    const {packageStored}=await chrome.storage.session.get('packageStored');
    const pending=await read(),count=(packageStored?.count||0)+pending.length;
    await chrome.action.setBadgeText({text:error?'!':count?String(count):''});
    if(!error)await chrome.action.setBadgeBackgroundColor({color:'#287c67'});
  }
  async function change(id,patch){
    await mutate(async()=>{const items=await read();const item=items.find(i=>i.id===id);if(item)Object.assign(item,patch);await chrome.storage.session.set({packagePending:items});});
  }
  async function backgroundTab(seedUrl){
    const tabs=await chrome.tabs.query({url:permissionOrigin(seedUrl)});
    const existing=selectSeedTab(tabs,seedUrl);
    if(existing)return existing;
    const tab=await chrome.tabs.create({url:seedUrl,active:true});
    await chrome.windows.update(tab.windowId,{focused:true});
    return tab;
  }
  async function requestLogin(tab,reload=false){
    if(!loginShown.has(tab.id)){
      loginShown.add(tab.id);
      await chrome.tabs.update(tab.id,{active:true,...(reload?{url:tab.url}:{})});
      await chrome.windows.update(tab.windowId,{focused:true});
    }
    await note('Log ind i FjordSeed for at gemme pakken. Dine valgte links venter her.',true);
  }
  async function process(){
    if(processing){rerun=true;return;}processing=true;
    try{
      while(true){
        const item=(await read()).find(i=>!i.error);
        if(!item)return;
        if(Date.now()-item.created>=MAX_AGE){
          await change(item.id,{error:'Overførslen udløb. Fjern ventende links og vælg torrenten igen.'});
          await note('Et ventende link udløb efter 15 minutter. Allerede gemte torrents ligger stadig i FjordSeed.',true);continue;
        }
        try{
          if(!await chrome.permissions.contains({origins:[permissionOrigin(item.seedUrl)]}))throw Error('Gem FjordSeed-adressen igen for at give adgang.');
          const tab=await backgroundTab(item.seedUrl);
          if(tab.status!=='complete'){await note('Pakken venter på FjordSeed.');return;}
          const auth=await chrome.scripting.executeScript({target:{tabId:tab.id},func:async expectedOrigin=>{
            if(location.origin!==expectedOrigin)return 'wrong-host';
            if(!document.querySelector('#add-form'))return 'login';
            const response=await fetch('/api/manual-package',{signal:AbortSignal.timeout(20000)});
            return response.status===401||response.status===403?'expired':response.ok?'ready':'error';
          },args:[new URL(item.seedUrl).origin]});
          if(['login','expired'].includes(auth[0]?.result)){await requestLogin(tab,auth[0].result==='expired');return;}
          if(auth[0]?.result!=='ready')throw Error('FjordSeed kunne ikke kontaktes. Opdatér FjordSeed eller prøv igen.');
          loginShown.delete(tab.id);
          if(!item.base64){
            const link=torrentLink(item.url),tracker=TRACKER_ORIGINS[new URL(link).origin];
            const response=await fetch(link,{credentials:'include',redirect:'error',cache:'no-store',signal:AbortSignal.timeout(20000)});
            const base64=await readTorrent(response,tracker);
            // Session storage also holds the existing direct-link transfer.
            if(await chrome.storage.session.getBytesInUse(null)+base64.length>8*1024*1024)throw Error('Ventende filer fylder for meget. Overfør eller ryd dem før du vælger flere.');
            Object.assign(item,{base64,name:`${tracker}-${new URL(link).pathname.split('/').filter(Boolean).at(-1)}.torrent`,url:null});
            await change(item.id,{base64:item.base64,name:item.name,url:null});
          }
          const results=await chrome.scripting.executeScript({target:{tabId:tab.id},func:stageTorrent,args:[item.base64,item.name,new URL(item.seedUrl).origin]});
          const outcome=results[0]?.result;
          if(outcome?.status==='stored'){
            await mutate(async()=>{
              await chrome.storage.session.set({packagePending:(await read()).filter(i=>i.id!==item.id),packageStored:{seedUrl:item.seedUrl,count:outcome.count}});
            });
            await note(`${outcome.count} torrents ligger klar i FjordSeed.${outcome.duplicate?' Torrenten var allerede i pakken.':''} Ingen download er startet.`);
          }else if(outcome?.status==='login'){
            await requestLogin(tab,true);return;
          }else{
            throw Error(outcome?.message||(outcome?.status==='incompatible'?'Opdatér FjordSeed for at bruge torrentpakker.':'Pakken kunne ikke overføres. Prøv igen fra udvidelsen.'));
          }
        }catch(error){
          // Keep a failed selection for an explicit retry; later clicks can proceed.
          const message=error.message?.includes('fetch')?'Torrentfilen kunne ikke hentes. Kontrollér tracker-login og forbindelsen.':error.message;
          await change(item.id,{error:message});await note(message,true);
        }
      }
    }finally{processing=false;if(rerun){rerun=false;void process().catch(()=>note('Pakken venter. Prøv overførslen igen.',true));}}
  }
  async function enqueue(value){
    const url=torrentLink(value),seedUrl=await destination();
    await mutate(async()=>{
      const items=await read();
      if(items.some(item=>item.seedUrl!==seedUrl))throw Error('Overfør eller ryd de ventende links til den tidligere FjordSeed-adresse først.');
      if(items.length>=50)throw Error('Der kan højst vente 50 torrentlinks. Åbn FjordSeed for at fortsætte.');
      const source=new URL(url).origin+new URL(url).pathname;
      const existing=items.find(item=>item.source===source);
      if(existing){delete existing.error;existing.created=Date.now();}
      else items.push({id:crypto.randomUUID(),url,source,seedUrl,created:Date.now()});
      await chrome.storage.session.set({packagePending:items});
    });
    await note('Føjet til pakken. Sender til FjordSeed i baggrunden…');
    await process();
  }
  async function retry(){
    await mutate(async()=>{const items=await read();for(const item of items)delete item.error;await chrome.storage.session.set({packagePending:items});});
    await process();
  }
  async function open(){
    const pending=await read(),stored=(await chrome.storage.session.get('packageStored')).packageStored;
    const seedUrl=pending[0]?.seedUrl||stored?.seedUrl||await destination();
    const tab=await backgroundTab(seedUrl);
    await chrome.tabs.update(tab.id,{active:true});await chrome.windows.update(tab.windowId,{focused:true});
    await retry();
  }
  async function clear(){
    if(processing)throw Error('Vent, til den igangværende overførsel er færdig.');
    await mutate(()=>chrome.storage.session.remove('packagePending'));
    await note('Ventende links ryddet. Allerede gemte torrents ligger stadig i FjordSeed.');
  }
  return {enqueue,process,retry,open,clear};
}
