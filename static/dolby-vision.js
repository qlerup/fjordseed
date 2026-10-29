(() => {
 let items=[],busy=false;
 const list=document.getElementById('dolby-vision-list'),status=document.getElementById('dolby-vision-status'),error=document.getElementById('dolby-vision-error'),search=document.getElementById('dolby-vision-search');
 if(!list)return;
 function el(tag,cls,text){const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;}
 function render(){
  list.replaceChildren();
  const query=search.value.toLocaleLowerCase('da');
  const visible=items.filter(x=>x.name.toLocaleLowerCase('da').includes(query));
  status.textContent=items.length?visible.length+' af '+items.length+' konverteringer':'Ingen konverteringer med gemte Dolby Vision-data endnu.';
  for(const item of visible){
   const row=el('div','workspace-job',''),copy=el('div','workspace-job-copy','');
   copy.append(el('strong','workspace-job-name',item.name),el('p','muted small',item.detail||''));row.append(copy);
   const active=['queued','restoring'].includes(item.state);
   const button=el('button','secondary',item.state==='restored'?'Gendannet':active?'Arbejder …':item.state==='error'?'Prøv gendannelse igen':'Gendan Dolby Vision');
   button.type='button';button.disabled=active||item.state==='restored';
   button.addEventListener('click',async()=>{
    button.disabled=true;error.hidden=true;
    try{await api('/api/conversion/dolby-vision/'+encodeURIComponent(item.id)+'/restore',{method:'POST',body:JSON.stringify({})});await load();}
    catch(e){error.textContent=e.message;error.hidden=false;button.disabled=false;}
   });row.append(button);list.append(row);
  }
 }
 async function load(){
  if(busy)return;busy=true;
  try{const data=await api('/api/conversion/dolby-vision');items=data.items;error.hidden=true;render();if(data.truncated)status.textContent+=' · Listen er begrænset; nogle filer vises ikke.';}
  catch(e){error.textContent=e.message;error.hidden=false;}
  finally{busy=false;}
 }
 document.getElementById('dolby-vision-refresh').addEventListener('click',load);
 search.addEventListener('input',render);
 const refresh=()=>{if(location.hash==='#conversion'&&!document.hidden)load();};
 window.addEventListener('hashchange',refresh);setInterval(refresh,10000);refresh();
})();
