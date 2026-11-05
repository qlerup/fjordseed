/* Isolated selection-menu animation checks. Requires Node and Playwright. */
const {chromium}=require('playwright');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const read=file=>readFileSync(path.join(__dirname,'..',file),'utf8');

(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  for(const theme of ['fjord','nordic'])for(const width of [2560,1440,390])for(const reducedMotion of ['no-preference','reduce']){
   const page=await browser.newPage({viewport:{width,height:1000},reducedMotion}),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.setContent(`<html data-theme="${theme}"><body><main>${read('templates/_conversion_workflow.html')}</main></body></html>`);
   for(const css of ['style','theme','nordic','conversion-workflow'])await page.addStyleTag({content:read(`static/${css}.css`)});
   await page.evaluate(()=>{
    window.api=async()=>({items:[1,2].map(id=>({id:String(id),title:`Film ${id}`,name:`film-${id}.mkv`,eligible:true,size:1024**3,media:{format:{duration:'100'},streams:[]}})),jobs:[]});
   });
   await page.addScriptTag({content:read('static/conversion-workflow.js')});
   await page.locator('[data-mode="full"]').click();
   await page.waitForSelector('.cw-film input');
   const choose=(id,checked)=>page.evaluate(({id,checked})=>{
    const input=document.querySelector(`[data-file-id="${id}"] input`);
    input.checked=checked;input.dispatchEvent(new Event('change'));
   },{id,checked});
   const settled=()=>page.evaluate(async()=>{
    await Promise.allSettled(document.getElementById('cw-selection').getAnimations().map(a=>a.finished));
   });
   const hidden=()=>page.waitForFunction(()=>document.getElementById('cw-selection').hidden);
   const shown=()=>page.evaluate(()=>!document.getElementById('cw-selection').hidden);

   await choose('1',true);await settled();
   await choose('2',true);await choose('1',false);
   assert.equal(await shown(),true,'Removing one of two selections keeps the menu');
   await choose('2',false);
   if(reducedMotion==='no-preference'){
    assert.equal(await shown(),true,'Menu remains rendered during exit');
    assert.equal(await page.evaluate(async()=>{const animation=document.getElementById('cw-selection').getAnimations()[0];await animation.ready;return animation.playbackRate;}),-1);
    assert.equal(await page.evaluate(()=>document.getElementById('cw-selection').inert),true);
   }
   await hidden();

   // Reverse a partly completed entrance, then select again during its exit.
   await choose('1',true);await page.waitForTimeout(100);await choose('1',false);await choose('2',true);
   await settled();
   assert.equal(await shown(),true,'Reselecting cancels a pending hide');
   assert.equal(await page.evaluate(()=>document.getElementById('cw-selection').inert),false);
   await page.locator('#cw-clear-selected').click();await hidden();
   assert.equal(await page.locator('.cw-film input:checked').count(),0);
   assert.equal(await page.evaluate(()=>document.getElementById('cw-library').classList.contains('has-selection')),false);

   // Re-rendering while the menu exits must not restart or cancel its exit.
   await choose('1',true);await settled();await choose('1',false);
   await page.locator('#cw-search').fill('Film');await hidden();
   assert.deepEqual(errors,[]);
   console.log(`PASS ${theme} ${width}px ${reducedMotion}: reverse exit, partial selection, rapid reselection, clear and re-render`);
   await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
