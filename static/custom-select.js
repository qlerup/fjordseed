(() => {
 const controls=new WeakMap();
 let nextId=0, opened;
 const make=(tag,cls)=>{const element=document.createElement(tag);element.className=cls;return element;};
 function enhance(select){
  // The account provider already has the same custom appearance and keyboard UI.
  if(controls.has(select)||select.id==='tracker-provider')return;
  const id=select.id||'custom-select-'+(++nextId);
  if(!select.id)select.id=id;
  const labels=[...select.labels];
  const label=labels.map(item=>{
   const copy=item.cloneNode(true);
   copy.querySelectorAll('select,input,button,.custom-select').forEach(child=>child.remove());
   return copy.textContent.trim();
  }).filter(Boolean).join(' ')||select.getAttribute('aria-label')||'Vælg';
  const wrapper=make('span','custom-select');
  const trigger=make('button','tracker-select-trigger custom-select-trigger');
  const value=make('span','custom-select-value'),name=make('span','custom-select-label');
  const list=make('div','tracker-select-options custom-select-options');
  const feedback=make('span','custom-select-error');
  name.id=id+'-custom-label';name.textContent=label;
  value.id=id+'-custom-value';
  trigger.type='button';trigger.id=id+'-trigger';trigger.setAttribute('role','combobox');
  trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');
  trigger.setAttribute('aria-labelledby',name.id+' '+value.id);
  list.id=id+'-options';list.setAttribute('role','listbox');list.setAttribute('aria-labelledby',name.id);
  list.setAttribute('popover','manual');trigger.setAttribute('aria-controls',list.id);
  feedback.id=id+'-custom-error';feedback.hidden=true;feedback.setAttribute('role','alert');
  trigger.append(value);select.before(wrapper);wrapper.append(name,select,trigger,list,feedback);
  select.classList.add('custom-native-select');select.tabIndex=-1;select.setAttribute('aria-hidden','true');
  let signature='', search='', searchAt=0;
  const options=()=>[...select.options].filter(option=>!option.hidden&&!option.parentElement.hidden);
  const disabled=option=>option.disabled||option.parentElement.disabled;
  const items=()=>[...list.querySelectorAll('[role="option"]')].filter(item=>!item.disabled);
  function close(focus=false){
   if(list.matches(':popover-open'))list.hidePopover();
   if(trigger.getAttribute('aria-expanded')!=='false')trigger.setAttribute('aria-expanded','false');
   if(opened===control)opened=undefined;
   if(focus&&!trigger.disabled)trigger.focus();
  }
  function draw(){
   const choices=options();
   const next=JSON.stringify(choices.map(option=>[option.value,option.textContent,option.dataset.description,disabled(option),option.selected]));
   if(next===signature)return;
   signature=next;
   const focused=document.activeElement?.dataset?.value,scroll=list.scrollTop;
   list.replaceChildren(...choices.map((option,index)=>{
    const item=make('button','tracker-select-option custom-select-option');
    item.type='button';item.tabIndex=-1;item.id=id+'-option-'+index;item.dataset.value=option.value;
    item.setAttribute('role','option');item.setAttribute('aria-selected',String(option.selected));
    item.disabled=Boolean(disabled(option));
    if(option.dataset.description){
     const copy=make('span','custom-select-copy'),title=make('span','custom-select-title'),description=make('span','custom-select-description');
     title.textContent=option.textContent;description.textContent=option.dataset.description;
     description.id=item.id+'-description';
     item.setAttribute('aria-label',option.textContent);item.setAttribute('aria-describedby',description.id);
     copy.append(title,description);item.append(copy);
    }else item.textContent=option.textContent;
    item.onclick=event=>{
     event.preventDefault();
     if(item.disabled||select.matches(':disabled'))return;
     select.value=option.value;
     select.dispatchEvent(new Event('input',{bubbles:true}));
     select.dispatchEvent(new Event('change',{bubbles:true}));
     close(true);
    };
    return item;
   }));
   if(!choices.length){const empty=make('p','muted small custom-select-empty');empty.textContent='Ingen valgmuligheder';list.append(empty);}
   if(list.matches(':popover-open')&&focused!==undefined){
    [...list.children].find(item=>item.dataset.value===focused&&!item.disabled)?.focus({preventScroll:true});
    list.scrollTop=scroll;
   }
  }
  function sync(){
   const selected=select.selectedOptions[0]?.textContent||'Vælg…';
   if(value.textContent!==selected)value.textContent=selected;
   trigger.disabled=select.matches(':disabled');wrapper.hidden=select.hidden;
   trigger.setAttribute('aria-required',String(select.required));
   if(select.validity.valid){feedback.hidden=true;trigger.removeAttribute('aria-invalid');}
   const described=[select.getAttribute('aria-describedby'),feedback.hidden?'':feedback.id].filter(Boolean).join(' ');
   if(described)trigger.setAttribute('aria-describedby',described);else trigger.removeAttribute('aria-describedby');
   if(trigger.disabled||wrapper.hidden)close();
   if(list.matches(':popover-open'))draw();
  }
  function open(edge){
   sync();if(trigger.disabled||!trigger.getClientRects().length)return;
   if(opened&&opened!==control)opened.close();
   draw();
   const box=trigger.getBoundingClientRect();
   const desired=options().some(option=>option.dataset.description)?520:300;
   const below=innerHeight-box.bottom-12,above=box.top-12,up=below<desired&&above>below;
   list.style.width=Math.min(box.width,innerWidth-24)+'px';
   list.style.left=Math.max(12,Math.min(box.left,innerWidth-parseFloat(list.style.width)-12))+'px';
   list.style.maxHeight=Math.max(44,Math.min(desired,up?above:below))+'px';
   list.showPopover();list.style.top=(up?Math.max(6,box.top-list.getBoundingClientRect().height-5):box.bottom+5)+'px';
   trigger.setAttribute('aria-expanded','true');opened=control;
   const enabled=items();
   (edge==='end'?enabled.at(-1):edge==='home'?enabled[0]:enabled.find(item=>item.getAttribute('aria-selected')==='true')||enabled[0])?.focus({preventScroll:true});
   document.activeElement?.scrollIntoView({block:'nearest'});
  }
  function keyboard(event){
   const isOpen=list.matches(':popover-open');
   if(event.key==='Escape'&&isOpen){event.preventDefault();event.stopPropagation();close(true);return;}
   if(event.key==='Tab'&&isOpen){close(true);return;}
   if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
    event.preventDefault();
    if(!isOpen){open(event.key==='Home'?'home':event.key==='End'?'end':undefined);return;}
    const enabled=items(),index=enabled.indexOf(document.activeElement);
    const target=event.key==='Home'?0:event.key==='End'?enabled.length-1:(index+(event.key==='ArrowDown'?1:-1)+enabled.length)%enabled.length;
    enabled[target]?.focus({preventScroll:true});enabled[target]?.scrollIntoView({block:'nearest'});return;
   }
   if((event.key==='Enter'||event.key===' ')&&isOpen){
    event.preventDefault();if(list.contains(document.activeElement))document.activeElement.click();return;
   }
   if(event.key.length===1&&event.key!==' '&&!event.ctrlKey&&!event.altKey&&!event.metaKey){
    event.preventDefault();if(!isOpen)open();
    const now=performance.now();search=now-searchAt<700?search+event.key:event.key;searchAt=now;
    const match=items().find(item=>item.textContent.trim().toLocaleLowerCase().startsWith(search.toLocaleLowerCase()));
    match?.focus({preventScroll:true});match?.scrollIntoView({block:'nearest'});
   }
  }
  const control={sync,close,select,trigger,list};controls.set(select,control);
  trigger.onclick=()=>list.matches(':popover-open')?close():open();
  trigger.addEventListener('keydown',keyboard);list.addEventListener('keydown',keyboard);
  select.addEventListener('focus',()=>trigger.focus());
  select.addEventListener('change',sync);select.addEventListener('input',sync);
  select.addEventListener('invalid',event=>{
   event.preventDefault();feedback.textContent=select.validationMessage;feedback.hidden=false;
   trigger.setAttribute('aria-invalid','true');sync();trigger.focus();
  });
  // Native selects remain the form's data source. Reflect programmatic updates
  // immediately, including values changed while opening/editing dialogs.
  for(const property of ['value','selectedIndex']){
   const descriptor=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,property);
   Object.defineProperty(select,property,{configurable:true,get(){return descriptor.get.call(this);},set(next){descriptor.set.call(this,next);sync();}});
  }
  new MutationObserver(sync).observe(select,{subtree:true,childList:true,characterData:true,attributes:true,
   attributeFilter:['disabled','hidden','selected','label','value','required','aria-describedby','data-description']});
  select.form?.addEventListener('reset',()=>queueMicrotask(()=>{close();feedback.hidden=true;sync();}));
  sync();
 }
 function scan(root){
  if(root.matches?.('select'))enhance(root);
  root.querySelectorAll?.('select').forEach(enhance);
 }
 scan(document);
 new MutationObserver(records=>{
  for(const record of records)for(const added of record.addedNodes)if(added.nodeType===1)scan(added);
 }).observe(document.body,{childList:true,subtree:true});
 document.addEventListener('pointerdown',event=>{
  if(opened&&!opened.trigger.contains(event.target)&&!opened.list.contains(event.target))opened.close();
 });
 document.addEventListener('focusin',event=>{
  if(opened&&event.target!==opened.trigger&&!opened.list.contains(event.target))opened.close();
 });
 document.addEventListener('scroll',event=>{if(opened&&!opened.list.contains(event.target))opened.close();},true);
 document.addEventListener('close',event=>{if(opened&&opened.select.closest('dialog')===event.target)opened.close();},true);
 window.addEventListener('resize',()=>opened?.close());
})();
