"""Size-only RSS creation/editing without tracker credentials, desktop and mobile."""
import sys,tempfile,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime
with tempfile.TemporaryDirectory() as folder:
 app=create_app(folder,testing=True,runtime_factory=FakeRuntime)
 server=make_server('127.0.0.1',0,app,threaded=True)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch();page=browser.new_page();errors=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('[name=username]').fill('admin')
   page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
   page.get_by_role('button',name='Log ind').click()
   page.goto(f'http://127.0.0.1:{server.server_port}/#rss')
   page.set_viewport_size({'width':1440,'height':1000})
   page.locator('#rss-new').click()
   expect(page.locator('#rss-max-size')).to_be_visible()
   page.locator('#rss-name').fill('Size controlled feed')
   page.locator('#rss-url').fill('https://tracker.example/rss')
   page.locator('#rss-max-size').fill('8.5')
   page.locator('#rss-enabled').check()
   page.locator('#rss-save').click()
   expect(page.locator('#rss-dialog')).not_to_be_visible()
   expect(page.locator('#rss-feed-list')).to_contain_text('8,5 GB')
   assert app.extensions['rss'].entries()[0]['max_size_gb']==8.5
   for width,value in [(1440,'12'),(390,'5.25')]:
    page.set_viewport_size({'width':width,'height':1000})
    page.locator('#rss-feed-list .tracker-actions .secondary').click()
    expect(page.locator('#rss-max-size')).to_have_value('8.5' if width==1440 else '12')
    page.locator('#rss-max-size').fill(value)
    screenshots=Path(__file__).resolve().parents[1]/'test-results';screenshots.mkdir(exist_ok=True)
    page.screenshot(path=str(screenshots/f'rss-size-{width}.png'))
    assert page.locator('#rss-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
    page.locator('#rss-save').click()
    expect(page.locator('#rss-dialog')).not_to_be_visible()
    assert app.extensions['rss'].entries()[0]['max_size_gb']==float(value)
   page.reload()
   page.locator('#rss-feed-list .tracker-actions .secondary').click()
   expect(page.locator('#rss-max-size')).to_have_value('5.25')
   page.locator('#rss-max-size').fill('')
   page.locator('#rss-save').click()
   expect(page.locator('#rss-dialog')).not_to_be_visible()
   assert app.extensions['rss'].entries()[0]['max_size_gb']==0
   assert not errors,errors
   browser.close()
 finally:server.shutdown()
print('PASS size-only RSS create/edit/reload/clear at desktop/mobile widths without tracker API keys')
