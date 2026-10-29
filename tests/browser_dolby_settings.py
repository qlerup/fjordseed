from pathlib import Path
from playwright.sync_api import sync_playwright,expect
root=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
 browser=p.chromium.launch()
 for width in (390,1440):
  page=browser.new_page(viewport={'width':width,'height':1000})
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.set_content((root/'templates/conversion_settings.html').read_text().replace('id="conversion-view" hidden','id="conversion-view"'))
  for name in ('style.css','library-conversion.css'):page.add_style_tag(content=(root/'static'/name).read_text())
  page.evaluate('''() => {
   location.hash='#conversion';window.$=s=>document.querySelector(s);
   window.node=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
   window.toast=()=>{};window.error=(s,e)=>{throw e;};
   window.data={conversion_target:'pc',conversion_dolby_vision:'separate',devices:[{id:'pc',name:'PC',online:true,conversion_version:1,media_folder:'M:/Films',files_updated_at:1793300000,files:[{name:'DV.mkv',size:123},{name:'HDR.mkv',size:456},{name:'Unknown.mkv',size:789}]}]};
   window.api=async(url,options)=>{
    if(url.endsWith('/bitrates'))return {media_folder:'M:/Films',pending:false,files:[{name:'DV.mkv',size:123,state:'ready',video_bps:60000000,dolby_vision:true,dolby_vision_profile:'7',dolby_vision_supported:true},{name:'HDR.mkv',size:456,state:'ready',video_bps:30000000,dolby_vision:false},{name:'Unknown.mkv',size:789,state:'unavailable'}]};
    if(url==='/api/conversion'&&options){window.saved=JSON.parse(options.body);Object.assign(data,saved);}
    return data;
   };
  }''')
  page.add_script_tag(content=(root/'static/conversion-settings.js').read_text())
  expect(page.locator('#conversion-dolby-vision')).to_have_value('separate')
  expect(page.locator('.workspace-file').filter(has_text='DV.mkv')).to_contain_text('Dolby Vision 7')
  expect(page.locator('.workspace-file').filter(has_text='HDR.mkv')).to_contain_text('Ingen Dolby Vision')
  expect(page.locator('.workspace-file').filter(has_text='Unknown.mkv')).to_contain_text('Dolby Vision: ukendt')
  page.locator('#conversion-dolby-vision').select_option('preserve')
  page.get_by_role('button',name='Gem konvertering',exact=True).click()
  assert page.evaluate('saved.conversion_dolby_vision')=='preserve'
  expect(page.locator('#conversion-dolby-vision')).to_have_value('preserve')
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  assert not errors,errors
  page.close()
 browser.close()
print('Dolby mode save and media detection passed on mobile and desktop')
