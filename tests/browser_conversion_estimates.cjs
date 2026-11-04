/* Isolated UI contract test. Run with Node and Playwright installed. */
const {chromium}=require('playwright');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const read=p=>readFileSync(path.join(root,p),'utf8');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  for(const theme of ['fjord','nordic','viking'])for(const width of [320,390,1440]){
   const page=await browser.newPage({viewport:{width,height:1000}}),errors=[];
   page.on('pageerror',e=>errors.push(e.message));
   await page.setContent(read('templates/conversion_settings.html').replace('id="conversion-view" hidden','id="conversion-view"'));
   await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
   for(const css of ['style','theme','library-conversion','nordic','viking'])await page.addStyleTag({content:read('static/'+css+'.css')});
   await page.evaluate(()=>{
    location.hash='#conversion';window.$=s=>document.querySelector(s);
    window.node=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
    window.data={conversion_bitrate:30,conversion_target:'server',devices:[{id:'pc',name:'PC',online:true,gpu_ready:true,conversion_version:3,media_folder:'M:/media',files_updated_at:1700000000,files:[{name:'Film.mkv',size:50*1024**3}]}]};
    window.metadata={state:'ready',name:'Film.mkv',size:50*1024**3,video_bps:60000000,total_bps:65000000,audio_tracks:[{index:0,stream_index:1,title:'Dansk Atmos <original>',codec:'truehd',output_codec:'truehd',language:'dan',channels:8,channel_layout:'7.1'},{index:1,stream_index:4,title:'',description:'English surround',codec:'aac',output_codec:'flac',language:'eng',channels:6,channel_layout:'5.1(side)'}],estimates:{20:{estimated_bytes:20*1024**3},30:{estimated_bytes:30*1024**3},40:{estimated_bytes:40*1024**3},audio:{estimated_bytes:null}}};
    window.api=async(url,options)=>{
     if(url.endsWith('/bitrates'))return {media_folder:'M:/media',files:[metadata]};
     if(url.endsWith('/select')){window.sent=JSON.parse(options.body);data.devices[0].queue=[{...sent,id:'q1',state:'queued'}];}
     return data;
    };
    window.toast=()=>{};window.error=(s,e)=>{throw e;};
    window.setInterval=(cb,ms)=>{if(ms===5000)window.poll=cb;};
   });
   await page.addScriptTag({content:read('static/conversion-settings.js')});
   await page.waitForFunction(()=>document.querySelector('.conversion-estimate strong')?.textContent==='Ca. 20 GiB');
   assert.equal(await page.locator('.conversion-estimate').count(),3);
   assert.match(await page.locator('.conversion-estimate.is-selected').innerText(),/30 Mbps/);
   assert.match(await page.locator('.conversion-audio-summary').innerText(),/dan.*8 kanaler.*eng.*6 kanaler/);
   for(const rate of ['20','30','40']){
    await page.selectOption('#library-conversion-bitrate',rate);
    assert.match(await page.locator('.conversion-estimate.is-selected').innerText(),new RegExp(rate+' Mbps'));
   }
   // Preserve independent library choices during background polling.
   await page.evaluate(()=>{data.devices[0].files_updated_at++;poll();});
   assert.equal(await page.inputValue('#library-conversion-bitrate'),'40');
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow '+theme+' '+width);
   // Verify video contract first, then reset queue for audio-only.
   await page.getByRole('button',{name:'Sæt i kø',exact:true}).click();
   assert.deepEqual(await page.evaluate(()=>({mode:sent.conversion_mode,bitrate:sent.bitrate})),{mode:'video',bitrate:40});
   await page.evaluate(()=>{data.devices[0].queue=[];poll();});
   await page.selectOption('#library-conversion-mode','audio');
   assert.ok(await page.locator('#library-conversion-bitrate-field').isHidden());
   assert.equal(await page.locator('.conversion-estimate').count(),1);
   assert.match(await page.locator('.conversion-estimate').innerText(),/Størrelse ukendt/);
   assert.match(await page.locator('.conversion-estimate-note').first().innerText(),/kan ikke estimeres sikkert/);
   const checks=page.locator('.conversion-audio-track input');
   assert.equal(await checks.count(),2);
   assert.ok(await checks.nth(0).isChecked());assert.ok(await checks.nth(1).isChecked());
   assert.match(await page.locator('.conversion-audio-track').first().innerText(),/Dansk Atmos <original>.*dan/s);
   assert.match(await page.locator('.conversion-audio-track').nth(1).innerText(),/English surround.*aac → flac/s);
   assert.match(await page.locator('#library-conversion-policy').innerText(),/FLAC/);
   await page.evaluate(()=>{metadata.audio_tracks[1].description='English surround updated';poll();});
   assert.match(await page.locator('.conversion-audio-track').nth(1).innerText(),/aac → flac/);
   assert.match(await page.locator('.conversion-audio-track').nth(1).innerText(),/English surround updated/);
   await checks.nth(0).uncheck();await checks.nth(1).uncheck();
   assert.ok(await page.getByRole('button',{name:'Sæt i kø',exact:true}).isDisabled());
   assert.match(await page.locator('.conversion-audio-tracks [role=status]').innerText(),/Vælg mindst ét/);
   await checks.nth(1).check();
   await page.evaluate(()=>{data.devices[0].files_updated_at++;poll();});
   assert.ok(!(await checks.nth(0).isChecked()));assert.ok(await checks.nth(1).isChecked());
   await page.selectOption('#library-conversion-mode','video');
   await page.selectOption('#library-conversion-mode','audio');
   assert.ok(!(await checks.nth(0).isChecked()));
   await page.evaluate(()=>{data.devices[0].conversion_version=2;poll();});
   assert.ok(await page.getByRole('button',{name:'Sæt i kø',exact:true}).isDisabled());
   await page.evaluate(()=>{data.devices[0].conversion_version=3;poll();});
   await page.getByRole('button',{name:'Sæt i kø',exact:true}).click();
   assert.equal(await page.evaluate(()=>sent.conversion_mode),'audio');
   assert.deepEqual(await page.evaluate(()=>sent.selected_audio_tracks),[1]);
   assert.match(await page.locator('.workspace-queue-row').innerText(),/Kun lyd/);
   await page.evaluate(()=>{data.devices[0].queue=[];metadata.audio_tracks[1].action='unsupported';metadata.audio_tracks[1].error='Ukendt kanalopsætning';poll();});
   assert.ok(await page.getByRole('button',{name:'Sæt i kø',exact:true}).isDisabled());
   assert.match(await page.locator('.conversion-audio-tracks [role=status]').innerText(),/Fravælg spor/);
   await checks.nth(0).check();await checks.nth(1).uncheck();
   assert.ok(await page.getByRole('button',{name:'Sæt i kø',exact:true}).isEnabled());
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   // Missing probe results must not turn into misleading zero-byte estimates.
   await page.evaluate(()=>{data.devices[0].media_folder='M:/other';data.devices[0].files_updated_at++;poll();});
   assert.ok(await page.getByRole('button',{name:'Sæt i kø',exact:true}).isDisabled());
   await page.selectOption('#library-conversion-mode','video');
   assert.match(await page.locator('.conversion-estimate').first().innerText(),/Beregner/);
   assert.deepEqual(errors,[]);
   await page.close();
  }
  console.log('PASS: 20/30/40 estimates, video/audio queue contracts, track selection/descriptions/unsupported tracks, missing metadata, polling and no overflow in 3 themes at 320/390/1440px');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
