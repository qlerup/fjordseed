/* Appearance is stored independently of VPN and torrent settings. */
(() => {
 'use strict';
 const root=document.documentElement, form=document.querySelector('#appearance-form');
 if(!form)return;
 form.addEventListener('submit',async event=>{
  event.preventDefault();
  const button=document.querySelector('#appearance-save'),error=document.querySelector('#appearance-error');
  const fields=[...form.querySelectorAll('input,button')];
  const value={theme:new FormData(form).get('theme'),animation:document.querySelector('#theme-animation').checked};
  fields.forEach(field=>field.disabled=true);error.hidden=true;button.textContent='Gemmer…';
  try{
   const response=await fetch('/api/appearance',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify(value)});
   const data=await response.json();
   if(!response.ok)throw new Error(data.error||'Temaet kunne ikke gemmes. Prøv igen.');
   root.dataset.theme=data.theme;root.dataset.animation=String(data.animation);
   document.querySelector('#battle-guide').hidden=data.theme!=='viking';
   const themeName={fjord:'Fjord',viking:'Viking',nordic:'Nordisk'}[data.theme]||'Fjord';
   document.querySelector('#appearance-status').textContent=`${themeName} er gemt. ${data.animation?'Levende baggrund er slået til.':'Baggrunden er sat på pause.'}`;
   document.dispatchEvent(new CustomEvent('fjordseed:appearance',{detail:data}));
  }catch(exc){error.textContent=exc.message;error.hidden=false;}
  finally{fields.forEach(field=>field.disabled=false);button.textContent='Gem tema';}
 });
})();
