"""Create/edit date-controlled RSS without tracker credentials, desktop/mobile."""
import sys,tempfile,threading
from datetime import datetime,timezone
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
   browser=p.chromium.launch();page=browser.new_page(timezone_id='Europe/Copenhagen');errors=[]
   page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('[name=username]').fill('admin')
   page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
   page.get_by_role('button',name='Log ind').click()
   page.goto(f'http://127.0.0.1:{server.server_port}/#rss')
   page.set_viewport_size({'width':1440,'height':1000})
   page.locator('#rss-new').click()
   assert page.locator('#rss-include, #rss-max-size, #rss-badge-area, #rss-min-leechers').count()==0
   page.locator('#rss-name').fill('Date controlled feed')
   page.locator('#rss-url').fill('https://tracker.example/rss')
   page.locator('#rss-start').select_option('3')
   page.locator('#rss-enabled').check()
   page.locator('#rss-save').click()
   expect(page.locator('#rss-dialog')).not_to_be_visible()
   expect(page.locator('#rss-feed-list')).to_contain_text('Hent fra:')
   original=app.extensions['rss'].entries()[0]['download_from']
   age=(datetime.now(timezone.utc)-datetime.fromisoformat(original)).total_seconds()
   assert 3*86400-5<age<3*86400+15
   for width,value in [(1440,'2026-10-07T14:30'),(390,'2026-01-07T14:30')]:
    page.set_viewport_size({'width':width,'height':844})
    page.locator('#rss-feed-list .tracker-actions .secondary').click()
    expect(page.locator('#rss-start')).to_have_value('custom')
    page.locator('#rss-start-date').fill(value)
    screenshots=Path(__file__).resolve().parents[1]/'test-results';screenshots.mkdir(exist_ok=True)
    page.screenshot(path=str(screenshots/f'rss-date-{width}.png'))
    assert page.locator('#rss-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
    page.locator('#rss-save').click()
    expect(page.locator('#rss-dialog')).not_to_be_visible()
    saved=app.extensions['rss'].entries()[0]['download_from']
    assert saved==('2026-10-07T12:30:00+00:00' if width==1440 else '2026-01-07T13:30:00+00:00')
    page.reload()
   page.locator('#rss-feed-list .tracker-actions .secondary').click()
   expect(page.locator('#rss-start-date')).to_have_value('2026-01-07T14:30')
   page.locator('#rss-save').click()
   expect(page.locator('#rss-dialog')).not_to_be_visible()
   assert app.extensions['rss'].entries()[0]['download_from']==saved
   page.locator('#rss-feed-list .tracker-actions .secondary').click()
   page.locator('#rss-start').select_option('all')
   expect(page.locator('#rss-start-date-label')).not_to_be_visible()
   page.locator('#rss-save').click()
   expect(page.locator('#rss-dialog')).not_to_be_visible()
   assert app.extensions['rss'].entries()[0]['download_from'] is None
   expect(page.locator('#rss-feed-list')).to_contain_text('Hent alle poster')
   assert not errors,errors
   browser.close()
 finally:server.shutdown()
print('PASS RSS date presets, fixed cutoff, local timezone/DST, save/edit/reload/all, desktop/mobile without tracker keys')
