/* Pure UI contract checks; no server or third-party packages required. */
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const source=readFileSync(require('node:path').join(__dirname,'../static/conversion-workflow.js'),'utf8');
const context=vm.createContext({Intl,document:{createElement(tag){return {tag,children:[],textContent:'',className:'',append(...children){this.children.push(...children);},classList:{add(){}}};}}});
vm.runInContext(source.slice(source.indexOf(' const $='),source.indexOf(' function visible()'))+'\nglobalThis.card=estimateCard;',context);
const GiB=1024**3;
const file={id:'film',size:50*GiB,media:{format:{duration:'7200'},streams:[{index:1,codec_type:'audio',codec_name:'aac',bit_rate:'192000',channels:2}]}};
const options={mode:'video',bitrate:20,audio:[1],audio_codec:'copy'};
const content=card=>card.children.map(c=>c.textContent).join(' | ');
let card=context.card(file,options,'20 Mbps');
assert.match(content(card),/20 Mbps.*Forventet slutstørrelse.*17,1 GiB.*Spar 32,9 GiB · 65,8 %/);
card=context.card({...file,size:GiB},options,'20 Mbps');
assert.match(content(card),/Ekstra plads: 16,1 GiB/);
assert.doesNotMatch(content(card),/Spar/);
card=context.card({...file,media:{...file.media,format:{}}},options,'20 Mbps');
assert.match(content(card),/Ukendt.*Varighed eller lydbitrate mangler/);
assert.doesNotMatch(content(card),/Spar|Ekstra plads/);
card=context.card(file,{...options,mode:'audio'},'Lydvalg');
assert.match(content(card),/50 GiB.*Uændret størrelse/);
card=context.card({...file,size:0},options,'20 Mbps');
assert.doesNotMatch(content(card),/Infinity|NaN|%/);
console.log('PASS: estimate values, savings and percentage, growth, missing metadata, unchanged audio and zero source size');

vm.runInContext('mode="video"; globalThis.compare=compareSavings;',context);
const ranked=[{...file,id:'growth',title:'A',size:GiB},{...file,id:'large',title:'Z',size:80*GiB},{...file,id:'unknown',title:'B',media:{...file.media,format:{}}},file].sort(context.compare);
assert.deepEqual(ranked.map(f=>f.id),['large','film','growth','unknown']);
console.log('PASS: savings sorted by absolute bytes, green savings before growth, unknown metadata last');
