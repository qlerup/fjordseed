"""Isolated seeding bar UI; no downloads or backend needed."""
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
source=(root/'static/app.js').read_text(encoding='utf-8')
start=source.index('function torrentStatus(')
end=source.index('\nfunction ',source.index('function card(')+1)
code="const current={ready:true}; function node(tag,cls,text){const n=document.createElement(tag);n.className=cls||'';if(text!==undefined)n.textContent=text;return n;}  function benefitView(){return node('div');} function eta(){return '10 minutter';}"+source[start:end]
code += source[source.index('function size(n)'):source.index('\nfunction ',source.index('function size(n)')+1)]
with sync_playwright() as p:
 browser=p.chromium.launch()
 page=browser.new_page()
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 for width in [390,1440]:
  if width==1440:
   page.close();page=browser.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
  page.set_viewport_size({'width':width,'height':900})
  page.set_content('<main></main>');page.add_style_tag(content=(root/'static/style.css').read_text(encoding='utf-8'));page.add_script_tag(content=code)
  for state,ratio,target,seconds,expected in [('stalledUP',1,2,0,.5),('uploading',1,5,0,.2),('stoppedUP',1,5,0,.2),('stalledUP',0,5,176400,1),('downloading',0,1,0,None),('stalledDL',0,1,0,None)]:
   page.evaluate("t=>document.querySelector('main').replaceChildren(card(t))",{'name':'Test Linux ISO','state':state,'progress':.42 if expected is None else 1,'size':1000,'ratio':ratio,'ratio_limit':target,'upspeed':0,'dlspeed':0,'seeding_time':seconds,'seeding_time_limit':2940,'uploaded':1024**3})
   bar=page.locator('.seed-progress')
   if expected is None:
    assert bar.count()==0
    assert page.locator('.torrent-progress .seed-state').inner_text() == ('Download \u2013 venter p\u00e5 peers' if state=='stalledDL' else 'Downloader')
    assert page.locator('.download-progress').evaluate('e=>e.value')==.42
   else:
    assert bar.evaluate('e=>e.value')==expected
    assert page.locator('.torrent-metrics dd').nth(2).inner_text() == str(ratio)+' / '+str(target)
    assert page.locator('.torrent-metrics dd').count()==5
    assert page.locator('.torrent-metrics dd').nth(4).inner_text()=='1.0 GB'
    assert page.locator('.torrent-meta').count()==0
    assert page.locator('.torrent').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
    assert page.locator('.seed-active').count()==(0 if state=='stoppedUP' else 1)
    assert bar.get_attribute('aria-label').startswith('Seeding')
    assert page.locator('.torrent-progress-track').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
    if expected==.5:
     folder=root/'test-results';folder.mkdir(exist_ok=True)
     page.screenshot(path=str(folder/f'seeding-bar-{width}.png'))
  page.evaluate("t=>document.querySelector('main').replaceChildren(card(t))",{
   'name':'Green Linux ISO','state':'stalledUP','progress':1,'size':1024**3,
   'ratio':1,'credited_ratio':.5,'ratio_limit':1,'uploaded':1024**3,'credited_uploaded':1024**3/2,
   'green_until':1900000000,'green_active':True,'seeding_time_limit':2940})
  assert page.locator('.seed-progress').evaluate('e=>e.value')==.5
  assert page.locator('.torrent-metrics dt').nth(2).inner_text()=='Krediteret ratio'
  assert page.locator('.torrent-metrics dd').nth(2).inner_text()=='0,5 / 1'
  assert page.locator('.torrent-metrics dd').nth(4).inner_text()=='1.0 GB'
  assert page.locator('.torrent-metrics dd').nth(5).inner_text()=='512 MB'
  assert '30 min. buffer' in page.locator('.torrent-details').inner_text()
  assert page.locator('.torrent').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
  page.screenshot(path=str(root/'test-results'/f'green-credit-{width}.png'))
 for power,unit in [(1,'KB'),(2,'MB'),(3,'GB'),(4,'TB')]:
  page.evaluate("uploaded=>document.querySelector('main').replaceChildren(card({name:'Upload check',state:'stalledUP',progress:1,uploaded}))",1024**power)
  assert page.locator('.torrent-metrics dd').nth(4).inner_text()=='1.0 '+unit
 assert not errors,errors
 browser.close()
 print('PASS layered progress, configured targets, time alternative, active/paused and downloads at 390/1440px')
