"""Manual minutes work in both themes; RSS cannot select this policy."""
from pathlib import Path
import sys, tempfile, threading, logging
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

logging.getLogger('werkzeug').setLevel(logging.ERROR)
root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as folder:
 app=create_app(folder,testing=True,runtime_factory=FakeRuntime)
 runtime=app.extensions['runtime'];original_status=runtime.status
 runtime.status=lambda:dict(original_status(),ready=True)
 server=make_server('127.0.0.1',0,app,threaded=True)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
   errors=[];requests=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.route('**/api/streaming',lambda route:route.fulfill(json={'conversion_enabled':False}))
   page.route('**/api/torrents/preview',lambda route:route.fulfill(json={'status':'unknown','matches':[],'ratio_estimates':[]}))
   page.route('**/api/torrents',lambda route:(requests.append(route.request.post_data),route.fulfill(json={'ok':True})))
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('[name=username]').fill('admin');page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
   page.get_by_role('button',name='Log ind',exact=True).click()
   for theme in ('fjord','viking'):
    page.goto(f'http://127.0.0.1:{server.server_port}/#appearance')
    page.locator(f'[name=theme][value={theme}]').check();page.locator('#appearance-save').click()
    expect(page.locator('html')).to_have_attribute('data-theme',theme)
    # Use the actual manual magnet form and submission sequence.
    page.goto(f'http://127.0.0.1:{server.server_port}/#torrents')
    page.locator('#new-torrent').click()
    page.locator('#method-magnet').click()
    page.locator('#magnet').fill('magnet:?xt=urn:btih:'+'c'*40)
    page.locator('#add-save').click()
    page.locator('#ratio-action').select_option('delete_time')
    expect(page.locator('#ratio-seed-minutes')).to_be_visible()
    expect(page.locator('#ratio-limit')).to_be_disabled()
    page.locator('#ratio-seed-minutes').fill('60')
    for width in (1440,390):
     page.set_viewport_size({'width':width,'height':1000})
     assert page.locator('#ratio-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
     page.screenshot(path=str(root/f'test-results/manual-minutes-{theme}-{width}.png'))
    page.locator('#ratio-save').click()
    expect(page.locator('#ratio-dialog')).not_to_be_visible()
    assert 'delete_time' in requests[-1]
    assert 'name="seed_minutes"\r\n\r\n60' in requests[-1]
    assert page.locator('#rss-action option[value=delete_time]').count()==0
    page.evaluate("openRatioEditor({hash:'cccccccccccccccccccccccccccccccccccccccc',name:'Timed',seed_minutes:60,ratio:100,seeding_time:1800,ratio_limit:1,share_limit_action:'RemoveWithContent'})")
    expect(page.locator('#edit-ratio-action')).to_have_value('delete_time')
    expect(page.locator('#edit-seed-minutes')).to_have_value('60')
    expect(page.locator('#edit-ratio-warning')).not_to_be_visible()
    page.locator('#edit-seed-minutes').fill('20');expect(page.locator('#edit-ratio-warning')).to_be_visible()
    page.evaluate("document.querySelector('#edit-ratio-dialog').close()")
   assert not errors,errors
   browser.close()
 finally:server.shutdown()
print('PASS manual minutes submission, both themes, responsive dialog, RSS exclusion and existing timer editing')
