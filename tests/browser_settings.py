"""Settings navigation keeps deep links, native history and mobile layout."""
from pathlib import Path
import sys,tempfile,threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as folder:
 app=create_app(folder,testing=True,runtime_factory=FakeRuntime)
 server=make_server('127.0.0.1',0,app,threaded=True)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
   errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('[name=username]').fill('admin')
   page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
   page.get_by_role('button',name='Log ind',exact=True).click()
   expect(page.locator('aside .nav')).to_have_count(3)
   expect(page.locator('#settings-tabs')).to_be_hidden()
   page.locator('.nav[href="#settings"]').click()
   expect(page.locator('#connection')).to_be_visible()
   expect(page.locator('#settings-tabs a[href="#connection"]')).to_have_attribute('aria-current','page')
   views={'connection':'connection','streaming':'streaming-view','storage':'storage-view','trackers':'trackers-view'}
   for width in (1440,390,320):
    page.set_viewport_size({'width':width,'height':1000})
    for route,ident in views.items():
     page.locator(f'#settings-tabs a[href="#{route}"]').click()
     expect(page.locator('#'+ident)).to_be_visible()
     for other in views.values():
      if other!=ident:expect(page.locator('#'+other)).to_be_hidden()
     expect(page.locator('#page-title')).to_have_text('Indstillinger')
     expect(page.locator('.nav[href="#settings"]')).to_have_attribute('aria-current','page')
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(root/f'test-results/settings-{width}.png'),full_page=True)
   page.reload()
   expect(page.locator('#trackers-view')).to_be_visible()
   page.locator('#settings-tabs a[href="#connection"]').click()
   page.go_back()
   expect(page.locator('#trackers-view')).to_be_visible()
   page.locator('.nav[href="#torrents"]').click()
   expect(page.locator('#settings-tabs')).to_be_hidden()
   expect(page.locator('#downloads-view')).to_be_visible()
   assert not errors,errors
   browser.close()
 finally:server.shutdown()
print('PASS settings tabs, deep links, reload/history, desktop and mobile 320/390px')
