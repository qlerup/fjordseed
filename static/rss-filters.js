let rssTitleFilters={include:[],exclude:[]},rssFilterDraft,rssFilterDrag;
const rssFilterSelected={include:new Set(),exclude:new Set()};
const rssFilterNames={include:'Kig efter',exclude:'Undgå'};
function rssFilterKey(value){return value.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').trim();}
function updateRssFilterSummary(){
 const {include,exclude}=rssTitleFilters;
 $('#rss-filter-summary').textContent=include.length||exclude.length?`${include.length} i Kig efter · ${exclude.length} i Undgå`:'Ingen titelfiltre — alle titler tillades';
}
function rssFilterError(message=''){
 $('#rss-filter-error').textContent=message;$('#rss-filter-error').hidden=!message;
}
function renderRssFilters(){
 for(const side of ['include','exclude']){
  const list=$('#rss-filter-'+side+'-list');list.replaceChildren();rssFilterSelected[side].clear();
  for(const [index,title] of rssFilterDraft[side].entries()){
   const row=node('li','rss-filter-item');row.draggable=true;row.dataset.filterIndex=index;
   const label=node('label'),check=node('input');check.type='checkbox';check.value=title;
   const handle=node('span','rss-filter-handle','⠿');handle.setAttribute('aria-hidden','true');
   label.append(check,handle,node('span','',title));row.append(label);list.append(row);
   check.onchange=()=>{if(check.checked)rssFilterSelected[side].add(title);else rssFilterSelected[side].delete(title);updateRssFilterActions(side);};
   row.ondragstart=event=>{rssFilterDrag={side,index};event.dataTransfer.setData('text/plain',title);event.dataTransfer.effectAllowed='move';row.classList.add('is-dragging');};
   row.ondragend=()=>{rssFilterDrag=null;document.querySelectorAll('.rss-filter-column').forEach(column=>column.classList.remove('is-drop-target'));row.classList.remove('is-dragging');};
  }
  if(!rssFilterDraft[side].length)list.append(node('li','rss-filter-empty',side==='include'?'Alle titler tillades':'Ingen titler udelukkes'));
  $('#rss-filter-'+side+'-count').textContent=rssFilterDraft[side].length+' / 50';
  updateRssFilterActions(side);
 }
}
function updateRssFilterActions(side){
 for(const action of ['remove','move'])$('#rss-filter-'+side+'-'+action).disabled=!rssFilterSelected[side].size;
}
function moveRssFilters(from,to,titles){
 const additions=titles.filter(title=>!rssFilterDraft[to].some(t=>rssFilterKey(t)===rssFilterKey(title)));
 if(rssFilterDraft[to].length+additions.length>50){rssFilterError('Der er højst plads til 50 titler i hver liste.');return;}
 rssFilterDraft[from]=rssFilterDraft[from].filter(title=>!titles.includes(title));
 rssFilterDraft[to].push(...additions);rssFilterError();renderRssFilters();
 $('#rss-filter-'+to+'-input').focus();
}
$('#rss-open-filters').onclick=()=>{
 rssFilterDraft={include:[...rssTitleFilters.include],exclude:[...rssTitleFilters.exclude]};
 rssFilterError();for(const side of ['include','exclude'])$('#rss-filter-'+side+'-input').value='';
 renderRssFilters();$('#rss-filter-dialog').showModal();$('#rss-filter-include-input').focus();
};
for(const side of ['include','exclude']){
 const input=$('#rss-filter-'+side+'-input'),column=$('#rss-filter-'+side+'-column');
 function add(){
  const title=input.value.trim(),key=rssFilterKey(title);
  if(!title||title.length>120||!key||/[\u0000-\u001f]/.test(title)){rssFilterError('Indtast en titel på 1–120 tegn.');input.focus();return;}
  for(const other of ['include','exclude'])if(rssFilterDraft[other].some(t=>rssFilterKey(t)===key)){rssFilterError('Titlen findes allerede i '+rssFilterNames[other]+'. Flyt den mellem listerne, hvis du vil ændre den.');input.focus();return;}
  if(rssFilterDraft[side].length>=50){rssFilterError('Der er højst plads til 50 titler i hver liste.');return;}
  rssFilterDraft[side].push(title);input.value='';rssFilterError();renderRssFilters();input.focus();
 }
 $('#rss-filter-'+side+'-add').onclick=add;
 input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();add();}};
 $('#rss-filter-'+side+'-remove').onclick=()=>{rssFilterDraft[side]=rssFilterDraft[side].filter(t=>!rssFilterSelected[side].has(t));rssFilterError();renderRssFilters();input.focus();};
 $('#rss-filter-'+side+'-move').onclick=()=>moveRssFilters(side,side==='include'?'exclude':'include',[...rssFilterSelected[side]]);
 column.ondragover=event=>{if(!rssFilterDrag)return;event.preventDefault();event.dataTransfer.dropEffect='move';column.classList.add('is-drop-target');};
 column.ondragleave=event=>{if(!column.contains(event.relatedTarget))column.classList.remove('is-drop-target');};
 column.ondrop=event=>{
  event.preventDefault();column.classList.remove('is-drop-target');
  if(!rssFilterDrag||rssFilterDrag.side===side)return;
  const {side:from,index}=rssFilterDrag,title=rssFilterDraft[from][index];rssFilterDrag=null;
  if(title!==undefined)moveRssFilters(from,side,[title]);
 };
}
$('#rss-filter-apply').onclick=()=>{rssTitleFilters={include:[...rssFilterDraft.include],exclude:[...rssFilterDraft.exclude]};updateRssFilterSummary();$('#rss-filter-dialog').close();};
$('#rss-filter-dialog').addEventListener('close',()=>{rssFilterDrag=null;$('#rss-open-filters').focus();});
updateRssFilterSummary();
