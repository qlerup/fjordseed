"""Exercise the subtitle picker, multi-film wizard, auth guide and mobile layout."""
from pathlib import Path, PurePosixPath
import argparse, sys, tempfile, threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

artifacts=Path(__file__).resolve().parents[1]/'test-results'/'subtitle-translation'
artifacts.mkdir(parents=True,exist_ok=True)
parser=argparse.ArgumentParser()
parser.add_argument('--theme',choices=['fjord','nordic'],default='nordic')
theme=parser.parse_args().theme
tracks=[{'id':'stream:3','language':'en','codec':'hdmv_pgs_subtitle','kind':'embedded','forced':False,'supported':True,'label':'English'},
        {'id':'file:Film.da.srt','language':'da','codec':'srt','kind':'sidecar','forced':False,'supported':True,'label':'Film.da.srt'}]
items=[{'id':str(i),'name':f'Film-{i}.mkv','title':f'Film {i} · Rejsen gennem fjorden','eligible':True,'size':1234,
    'tracks':tracks,'probed':True,'snapshot':'stamp','fingerprint':['1234','1'],'preferred':'stream:3'} for i in range(1,3)]
auth={'connected':True,'enabled':True,'active':'oaiapp_test','revision':1,'accounts':[{'id':'oaiapp_test','email':'Testkonto','connected':True}]}
empty=[dict(items[0],id='empty-'+str(i),title='A empty '+str(i),tracks=[],probed=False) for i in range(45)]
hidden=dict(items[0],id='hidden',title='Z discovered',tracks=[],probed=False)
library=empty+items+[hidden]
def detail(route):
 ident=route.request.url.rsplit('/',1)[1]
 item=next(i for i in library if i['id']==ident)
 route.fulfill(json=dict(item,probed=True,tracks=tracks if ident=='hidden' else item['tracks']))
class Demo(FakeRuntime):
 host_downloads=PurePosixPath('/downloads')
 def status(self): return {**super().status(),'enabled':True,'ready':True}
with tempfile.TemporaryDirectory() as folder:
 app=create_app(folder,testing=True,runtime_factory=Demo)
 server=make_server('127.0.0.1',0,app,threaded=False)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch(); page=browser.new_page(viewport={'width':1440,'height':1000}); errors=[]; submitted=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.route('**/api/subtitles/library',lambda r:r.fulfill(json={'items':library,'truncated':False}))
   page.route('**/api/subtitles/library/*',detail)
   page.route('**/api/subtitles/jobs',lambda r:r.fulfill(json={'jobs':[],'languages':{'en':'Engelsk','da':'Dansk','sv':'Svensk','de':'Tysk'},'auth':auth}))
   page.route('**/api/subtitles/models?*',lambda r:r.fulfill(json={'models':[{'id':'test-model','name':'Testmodel'}]}))
   def login(route):
    auth['login']={'state':'waiting','user_code':'ABCD-1234','verification_url':'https://auth.openai.com/codex/device'}
    route.fulfill(json={**auth,'login':{'state':'starting'}})
   page.route('**/api/subtitles/auth/device',login)
   page.context.route('https://auth.openai.com/**',lambda r:r.fulfill(body='Mock OpenAI login'))
   page.route('**/api/subtitles/auth/cancel',lambda r:(auth.pop('login',None),r.fulfill(json={'ok':True})))
   page.route('**/api/conversion/workflow',lambda r:r.fulfill(json={'items':[],'jobs':[]}))
   def queue(route): submitted.append(route.request.post_data_json);route.fulfill(json={'ok':True})
   page.route('**/api/subtitles/queue',queue)
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('[name=username]').fill('admin');page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip());page.get_by_role('button',name='Log ind',exact=True).click()
   page.goto(f'http://127.0.0.1:{server.server_port}/#appearance')
   page.locator(f'[name=theme][value={theme}]').check();page.locator('#appearance-save').click()
   expect(page.locator('#appearance-status')).to_contain_text('er gemt');page.reload()
   page.goto(f'http://127.0.0.1:{server.server_port}/#conversion');page.locator('#st-open').click()
   expect(page.locator('.st-film')).to_have_count(3)
   expect(page.locator('#st-films')).not_to_contain_text('A empty')
   expect(page.locator('#st-model')).to_have_value('test-model')
   for width in (1440,390,320):
    page.set_viewport_size({'width':width,'height':1000})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'overflow at {width}'
    page.screenshot(path=str(artifacts/f'{theme}-library-{width}.png'),full_page=True)
   page.locator('.st-film input[type=checkbox]').nth(0).check();page.locator('.st-film input[type=checkbox]').nth(1).check();page.locator('#st-configure').click()
   expect(page.locator('#st-dialog')).to_be_visible()
   page.locator('.st-languages summary').click()
   expect(page.get_by_label('Dansk · findes allerede')).to_be_disabled()
   page.get_by_label('Svensk',exact=True).check();page.get_by_label('Tysk',exact=True).check()
   page.screenshot(path=str(artifacts/f'{theme}-languages-mobile.png'),full_page=True)
   page.locator('#st-next').click();page.locator('.st-languages summary').click();page.get_by_label('Tysk',exact=True).check()
   page.locator('#st-next').click();expect(page.locator('#st-fields')).to_contain_text('Nye sprog: Svensk, Tysk')
   page.locator('#st-next').click();expect(page.locator('#st-dialog')).to_be_hidden()
   assert [i['targets'] for i in submitted[0]['items']]==[['sv','de'],['de']]
   assert all(i['source']=='stream:3' for i in submitted[0]['items'])
   page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true})")
   with page.expect_popup() as popup:
    page.locator('#st-login').click()
   expect(page.locator('#st-login-guide')).to_be_visible()
   expect(popup.value).to_have_url('https://auth.openai.com/codex/device',timeout=12000)
   expect(page.locator('#st-login-code')).to_have_text('ABCD-1234')
   expect(page.locator('#st-login-link')).to_have_attribute('href','https://auth.openai.com/codex/device')
   for width in (1440,390,320):
    page.set_viewport_size({'width':width,'height':1000})
    assert page.locator('#st-login-code').evaluate('(e)=>parseFloat(getComputedStyle(e).fontSize)>=26')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),f'login overflow at {width}'
    page.locator('#st-device-details').screenshot(path=str(artifacts/f'{theme}-login-{width}.png'))
   page.wait_for_timeout(5200);expect(page.locator('#st-login-guide')).to_be_visible()
   page.locator('#st-login-cancel').click();expect(page.locator('#st-login-guide')).to_be_hidden()
   page.evaluate("delete document.hidden")
   page.locator('#st-back').click();expect(page.locator('#cw-cards')).to_be_visible()
   assert not errors,errors
   print('PASS: per-film languages, PGS/SRT, existing-language guard, login guide, 1440/390/320px, no JS errors')
   browser.close()
 finally: server.shutdown()
