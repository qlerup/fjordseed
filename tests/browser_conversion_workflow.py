"""Exercise the per-film wizard without modifying torrents or library files."""
from pathlib import Path, PurePosixPath
import copy, json, sys, tempfile, threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

media={'format':{'duration':'7200'},'streams':[
 {'index':0,'codec_type':'video','codec_name':'hevc','width':3840,'height':2160},
 {'index':1,'codec_type':'audio','codec_name':'truehd','channels':6,'channel_layout':'5.1','bit_rate':'4000000','tags':{'language':'eng'}},
 {'index':2,'codec_type':'audio','codec_name':'aac','channels':2,'bit_rate':'192000','tags':{'language':'dan'}},
 {'index':3,'codec_type':'subtitle','codec_name':'subrip','tags':{'language':'dan'}}]}
items=[{'id':str(i),'name':f'Film-{i}.mkv','title':f'Film {i} · En rejse gennem fjorden','size':50*1024**3,'eligible':True,'skipped_modes':[],'cover':None} for i in range(1,4)]
class Demo(FakeRuntime):
 host_downloads=PurePosixPath('/downloads')
 def status(self):return {**super().status(),'enabled':True,'ready':True}

with tempfile.TemporaryDirectory() as folder:
 app=create_app(folder,testing=True,runtime_factory=Demo)
 server=make_server('127.0.0.1',0,app,threaded=True)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];submitted=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.route('**/api/conversion/workflow',lambda r:r.fulfill(json={'items':copy.deepcopy(items),'jobs':[]}))
   page.route('**/api/conversion/workflow/*/media',lambda r:r.fulfill(json={'media':media,'fingerprint':[50*1024**3,1]}))
   def queue(route):submitted.append(route.request.post_data_json);route.fulfill(json={'ok':True})
   page.route('**/api/conversion/workflow/queue',queue)
   def skip(route):
    data=route.request.post_data_json
    for item in items:
     if item['id']==data['id']:item['skipped_modes']=[data['mode']] if data['skip'] else []
    route.fulfill(json={'ok':True})
   page.route('**/api/conversion/workflow/skip',skip)
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('[name=username]').fill('admin');page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip());page.get_by_role('button',name='Log ind',exact=True).click()
   page.goto(f'http://127.0.0.1:{server.server_port}/#conversion')
   for width in (1440,390,320):
    page.set_viewport_size({'width':width,'height':1000});expect(page.locator('#cw-cards')).to_be_visible()
    assert page.locator('.cw-card').count()==4
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=f'/tmp/fjordseed-conversion-cards-{width}.png',full_page=True)
   page.locator('[data-mode=full]').click();expect(page.locator('.cw-film')).to_have_count(3)
   expect(page.locator('.cw-film').first).to_contain_text('20 Mbps')
   page.locator('.cw-film input[type=checkbox]').nth(0).check();page.locator('.cw-film input[type=checkbox]').nth(1).check();page.locator('#cw-configure').click()
   expect(page.locator('#cw-step')).to_contain_text('FILM 1 AF 2')
   page.locator('#cw-fields select').first.select_option('20',force=True)
   expect(page.locator('.cw-live')).to_contain_text('GiB')
   for width in (1440,390,320):
    page.set_viewport_size({'width':width,'height':1000});assert page.locator('#cw-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    page.screenshot(path=f'/tmp/fjordseed-conversion-modal-{width}.png')
   page.locator('#cw-next').click();expect(page.locator('#cw-step')).to_contain_text('FILM 2 AF 2')
   page.locator('#cw-fields select').first.select_option('40',force=True)
   page.locator('#cw-next').click();expect(page.locator('#cw-dialog-title')).to_have_text('Gennemse din konverteringskø')
   page.locator('#cw-next').click();expect(page.locator('#cw-dialog')).not_to_be_visible()
   assert [i['options']['bitrate'] for i in submitted[0]['items']]==[20,40]
   page.locator('#cw-back').click();page.locator('[data-mode=audio]').click()
   expect(page.locator('.cw-film').first).not_to_contain_text('3840')
   page.locator('.cw-film').first.get_by_role('button',name='Spring over',exact=True).click();expect(page.locator('.cw-film')).to_have_count(2)
   page.locator('#cw-show-skipped').check();expect(page.locator('.cw-film')).to_have_count(3)
   page.locator('.cw-film').first.get_by_role('button',name='Gendan',exact=True).click()
   page.locator('.cw-film input[type=checkbox]').first.check();page.locator('#cw-configure').click()
   expect(page.locator('#cw-fields')).not_to_contain_text('Videobitrate');expect(page.locator('#cw-fields')).not_to_contain_text('Dolby Vision')
   expect(page.locator('#cw-fields')).to_contain_text('Lydsprog og spor')
   page.locator('#cw-close').click();page.locator('#cw-back').click();page.locator('[data-mode=video]').click()
   expect(page.locator('.cw-film').first).not_to_contain_text('TRUEHD')
   page.locator('.cw-film input[type=checkbox]').first.check();page.locator('#cw-configure').click()
   expect(page.locator('#cw-fields')).not_to_contain_text('Lydsprog og spor');expect(page.locator('#cw-fields')).to_contain_text('Videobitrate')
   page.locator('#cw-skip-film').click();expect(page.locator('#cw-next')).to_be_disabled()
   page.locator('#cw-close').click()
   # Wizard skip persists only in video; converted/manual films remain discoverable.
   page.locator('#cw-show-skipped').uncheck()
   expect(page.locator('.cw-film')).to_have_count(2)
   items.append({'id':'4','name':'Manual.mkv','title':'Manuel film','size':1000,'eligible':False,'source':'manual','skipped_modes':[]})
   items.append({'id':'5','name':'Converted.mkv','title':'Konverteret film','size':1000,'eligible':False,'converted':True,'completed_modes':['video'],'skipped_modes':[]})
   page.locator('#cw-refresh').click();expect(page.locator('.cw-film')).to_have_count(3)
   expect(page.locator('#cw-films')).to_contain_text('Manuelt tilføjet')
   page.locator('#cw-show-completed').check();expect(page.locator('.cw-film')).to_have_count(4)
   expect(page.locator('.cw-completed')).to_have_count(1)
   page.locator('#cw-show-completed').uncheck()
   page.locator('#cw-back').click();page.locator('[data-mode=audio]').click()
   expect(page.locator('.cw-film')).to_have_count(5)
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
   assert not errors,errors
   print('PASS: cards, responsive 1440/390/320, per-film settings, estimates, queue submission, skip/restore, audio/video boundaries; no JS errors')
   browser.close()
 finally:server.shutdown()
