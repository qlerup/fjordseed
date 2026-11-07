"""Exercise the per-film wizard without modifying torrents or library files."""
from pathlib import Path, PurePosixPath
import argparse, copy, json, sys, tempfile, threading, time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--theme',choices=('fjord','nordic'),default='nordic')
theme=parser.parse_args().theme
artifacts=Path(__file__).resolve().parents[1]/'test-results'/'conversion-workflow'
artifacts.mkdir(parents=True,exist_ok=True)

media={'format':{'duration':'7200'},'streams':[
 {'index':0,'codec_type':'video','codec_name':'hevc','width':3840,'height':2160},
 {'index':1,'codec_type':'audio','codec_name':'truehd','channels':6,'channel_layout':'5.1','bit_rate':'4000000','tags':{'language':'eng'}},
 {'index':2,'codec_type':'audio','codec_name':'aac','channels':2,'bit_rate':'192000','tags':{'language':'dan'}},
 {'index':3,'codec_type':'subtitle','codec_name':'subrip','tags':{'language':'dan'}}]}
items=[{'id':str(i),'name':f'Film-{i}.mkv','title':f'Film {i} · En rejse gennem fjorden','size':50*1024**3,'eligible':True,'skipped_modes':[],'cover':None} for i in range(1,4)]
items[2]['size']=512*1024**2
items[1]['size']=1024**3  # Conversion grows this file; the first film saves space.
items.reverse()  # Deliberately unsorted: largest saving must be shown first.
jobs=[]
class Demo(FakeRuntime):
 host_downloads=PurePosixPath('/downloads')
 def status(self):return {**super().status(),'enabled':True,'ready':True}

with tempfile.TemporaryDirectory() as folder:
 app=create_app(folder,testing=True,runtime_factory=Demo)
 # These mocked requests are short; serialize them to keep the browser check
 # usable in CI containers with a small process/thread allowance.
 server=make_server('127.0.0.1',0,app,threaded=False)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];submitted=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.route('**/api/conversion/workflow',lambda r:r.fulfill(json={'items':copy.deepcopy(items),'jobs':copy.deepcopy(jobs)}))
   page.route('**/api/conversion/workflow/*/media',lambda r:r.fulfill(json={'media':media,'fingerprint':[str(50*1024**3),'1794015885417718001']}))
   def queue(route):submitted.append(route.request.post_data_json);route.fulfill(json={'ok':True})
   page.route('**/api/conversion/workflow/queue',queue)
   def skip(route):
    data=route.request.post_data_json
    for item in items:
     if item['id'] in data.get('ids',[data.get('id')]):item['skipped_modes']=[data['mode']] if data['skip'] else []
    route.fulfill(json={'ok':True})
   page.route('**/api/conversion/workflow/skip',skip)
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('[name=username]').fill('admin');page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip());page.get_by_role('button',name='Log ind',exact=True).click()
   if theme!='fjord':
    page.goto(f'http://127.0.0.1:{server.server_port}/#appearance')
    page.locator(f'[name=theme][value={theme}]').check()
    page.locator('#appearance-save').click()
    expect(page.locator('#appearance-status')).to_contain_text('er gemt')
    page.reload()
   expect(page.locator('html')).to_have_attribute('data-theme',theme)
   page.goto(f'http://127.0.0.1:{server.server_port}/#conversion')
   page.locator('[data-mode=audio]').click()
   page.locator('.cw-film input[type=checkbox]').first.check();page.locator('#cw-configure').click()
   keep=page.get_by_role('group',name='Behold lyd',exact=True)
   convert=page.get_by_role('group',name='Konvertér lyd',exact=True)
   expect(keep.locator('input:checked')).to_have_count(2)
   expect(convert.locator('input:checked')).to_have_count(0)
   english=convert.get_by_role('group',name='eng',exact=False)
   danish=convert.get_by_role('group',name='dan',exact=False)
   english.get_by_label('E-AC3 (Dolby Digital Plus)',exact=True).check()
   english.get_by_label('AC3 (Dolby Digital)',exact=True).check()
   danish.get_by_label('AC3 (Dolby Digital)',exact=True).check()
   for check in keep.locator('input').all():check.uncheck()
   expect(convert).to_contain_text('0 originalspor · 3 konverterede spor')
   expect(page.locator('.cw-live')).to_contain_text('Groft tidsestimat')
   expect(page.locator('.cw-live')).to_contain_text('Ikke målt på serveren')
   for width in (1440,390,320):
    page.set_viewport_size({'width':width,'height':1000})
    assert page.locator('#cw-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    page.screenshot(path=str(artifacts/f'{theme}-audio-tracks-{width}.png'))
   page.locator('#cw-next').click()
   expect(page.locator('#cw-fields')).to_contain_text('Samlet tid · 1 valgte film')
   expect(page.locator('#cw-fields')).to_contain_text('Ca. ')
   for width in (1440,390,320):
    page.set_viewport_size({'width':width,'height':1000})
    assert page.locator('#cw-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    page.screenshot(path=str(artifacts/f'{theme}-time-review-{width}.png'))
   page.locator('#cw-prev').click()
   expect(convert.locator('input:checked')).to_have_count(3)
   expect(keep.locator('input:checked')).to_have_count(0)
   page.locator('#cw-next').click();page.locator('#cw-next').click()
   expect(page.locator('#cw-dialog')).not_to_be_visible()
   assert submitted[-1]['items'][0]['fingerprint']==[str(50*1024**3),'1794015885417718001']
   assert submitted[-1]['items'][0]['options']['audio']==[]
   assert submitted[-1]['items'][0]['options']['audio_conversions']=={'1':['eac3','ac3'],'2':['ac3']}
   saved_streams=copy.deepcopy(media['streams'])
   source=copy.deepcopy(media['streams'][1]);source['codec_name']='eac3'
   media['streams']=[media['streams'][0]]+[{**copy.deepcopy(source),'index':i,'tags':{'language':lang}} for i,lang in enumerate(('eng','dan','fin','nor','swe'),1)]
   page.locator('#cw-refresh').click()
   page.locator('.cw-film input[type=checkbox]').first.check();page.locator('#cw-configure').click()
   expect(keep.locator('input:checked')).to_have_count(5)
   expect(convert.locator('input:disabled')).to_have_count(5)
   expect(convert).to_contain_text('findes allerede')
   for check in convert.locator('input:enabled').all():check.check()
   expect(convert).to_contain_text('5 originalspor · 5 konverterede spor')
   page.set_viewport_size({'width':1440,'height':1000})
   page.screenshot(path=str(artifacts/f'{theme}-audio-eac3.png'))
   page.locator('#cw-close').click()
   jobs.append({'id':'progress-demo','name':'Progress test','options':{'mode':'audio'},'state':'running','phase':'encoding','stage':'audio_encoding','phase_progress':37.5,'progress':37.5,'eta_seconds':120,'at':time.time(),'detail':'Konverterer lyd'})
   page.locator('#cw-queue-refresh').click()
   expect(page.locator('#cw-jobs progress')).to_have_attribute('value','37.5')
   expect(page.locator('#cw-jobs')).to_contain_text('37,5 % af dette trin')
   expect(page.locator('#cw-jobs')).to_contain_text('ca. 2 min tilbage i dette trin')
   page.screenshot(path=str(artifacts/f'{theme}-live-progress.png'))
   jobs[0]['at']=time.time()-90
   page.locator('#cw-queue-refresh').click()
   expect(page.locator('#cw-jobs')).to_contain_text('afventer ny status')
   expect(page.locator('#cw-jobs')).not_to_contain_text('tilbage i dette trin')
   jobs[0].update(phase='queued',phase_progress=None,eta_seconds=None)
   page.locator('#cw-queue-refresh').click()
   expect(page.locator('#cw-jobs')).to_contain_text('konverteringen er ikke startet')
   expect(page.locator('#cw-jobs progress')).to_have_count(0)
   expect(page.locator('#cw-jobs')).not_to_contain_text('Arbejder')
   assert not errors,errors
   print('PASS: per-track audio, both formats, converted-only output, persisted selections, five EAC3 languages, mobile layouts; no JS errors')
   browser.close()
 finally:server.shutdown()
