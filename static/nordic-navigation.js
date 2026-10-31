/* Reuse the normal settings navigation as a second hanging sign. */
(() => {
 'use strict';
 const root=document.documentElement,aside=document.querySelector('body aside');
 const tabs=document.querySelector('#settings-tabs'),trigger=aside?.querySelector('[href="#settings"]');
 if(!aside||!tabs||!trigger)return;
 const home=document.createComment('settings navigation home');tabs.before(home);
 const signs=document.createElement('div');signs.className='navigation-signs';
 aside.before(signs);signs.append(aside);
 const hanger=document.createElement('div');hanger.className='settings-sign-hanger';hanger.hidden=true;
 signs.append(hanger);
 const settingsRoutes=new Set(['settings','connection','streaming','storage','trackers','conversion','appearance']);
 const isSettings=()=>settingsRoutes.has(location.hash.slice(1));
 let open=isSettings();
 function sync(){
  const nordic=root.dataset.theme==='nordic';
  if(nordic){
   if(tabs.parentNode!==hanger)hanger.append(tabs);
   trigger.setAttribute('aria-controls','settings-tabs');
   trigger.setAttribute('aria-expanded',String(isSettings()&&open));
  }else{
   if(tabs.parentNode!==home.parentNode)home.after(tabs);
   trigger.removeAttribute('aria-controls');trigger.removeAttribute('aria-expanded');
  }
  hanger.hidden=!nordic||!isSettings()||!open;
 }
 trigger.addEventListener('click',event=>{
  if(root.dataset.theme!=='nordic'||!isSettings()||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
  event.preventDefault();open=!open;sync();
 });
 signs.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&root.dataset.theme==='nordic'&&open){
   event.preventDefault();open=false;sync();trigger.focus({preventScroll:true});
  }
 });
 window.addEventListener('hashchange',()=>{open=isSettings();sync();});
 document.addEventListener('fjordseed:appearance',()=>{open=isSettings();sync();});
 sync();
})();
