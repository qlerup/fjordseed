"""Appearance persistence, background interaction, animation lifecycle and mobile layout."""
from pathlib import Path
import sys, tempfile, threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as folder:
 app = create_app(folder, testing=True, runtime_factory=FakeRuntime)
 app.extensions['runtime'].host_downloads=Path('/downloads')
 server = make_server('127.0.0.1', 0, app, threaded=True)
 threading.Thread(target=server.serve_forever, daemon=True).start()
 try:
  with sync_playwright() as p:
   browser = p.chromium.launch()
   page = browser.new_page(viewport={'width':1440,'height':1000})
   errors=[];page.on('pageerror', lambda e: errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('[name=username]').fill('admin')
   page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
   page.get_by_role('button',name='Log ind',exact=True).click()
   page.goto(f'http://127.0.0.1:{server.server_port}/#appearance')
   page.route('**/api/streaming',lambda route:route.fulfill(json={'conversion_enabled':False}))
   expect(page.locator('#appearance-view')).to_be_visible()
   expect(page.locator('html')).to_have_attribute('data-theme','fjord')
   page.locator('[name=theme][value=viking]').check()
   page.locator('#appearance-save').click()
   expect(page.locator('html')).to_have_attribute('data-theme','viking')
   expect(page.locator('.goat-mountain')).to_be_hidden()
   transform=page.locator('.viking-warrior').first.evaluate('e=>e.style.transform')
   page.wait_for_function('(before)=>document.querySelector(".viking-warrior").style.transform!==before',arg=transform)
   page.evaluate('document.querySelector("#add-dialog").showModal()')
   expect(page.locator('.viking-battle')).to_have_class('viking-battle is-paused')
   frozen=page.locator('.viking-warrior').first.evaluate('e=>e.style.transform')
   page.wait_for_timeout(120)
   assert page.locator('.viking-warrior').first.evaluate('e=>e.style.transform')==frozen
   page.evaluate('document.querySelector("#add-dialog").close()')
   page.emulate_media(reduced_motion='reduce')
   expect(page.locator('.viking-battle')).to_have_class('viking-battle is-paused')
   # Pause at arrival and use a visible actor in the free bottom margin.
   page.reload()
   expect(page.locator('html')).to_have_attribute('data-theme','viking')
   expect(page.locator('.viking-warrior:not([hidden])')).to_have_count(24)
   page.screenshot(path=str(root/'test-results/theme-viking-desktop.png'),full_page=True)
   # The settings form covers most of the background; test pointer targeting
   # in the empty downloads area, without relying on random spawn positions.
   page.locator('a[href="#torrents"]').click()
   expect(page.locator('#appearance-view')).to_be_hidden()
   page.screenshot(path=str(root/'test-results/viking-click-area.png'))
   hit=page.evaluate('''() => {
    const actors=[...document.querySelectorAll('.viking-warrior')];
    for(const el of [...actors].sort((a,b)=>Number(b.style.zIndex)-Number(a.style.zIndex)||actors.indexOf(b)-actors.indexOf(a))) {
     const r=el.getBoundingClientRect();
     for(const fraction of [.25,.5,.75]) {
      const x=r.left+r.width*fraction,y=r.top+r.height*.5,target=document.elementFromPoint(x,y);
      if(target&&!target.closest('a,input,select,textarea,dialog,aside,form,.connection,.torrent,.tracker-card,.insights,.stats,.settings-tabs')&&(!target.closest('button')||target.closest('.viking-warrior')))return {index:actors.indexOf(target.closest('.viking-warrior')||el),x,y};
     }
    }
   }''')
   assert hit, 'A warrior must be clickable in the background gutters'
   page.mouse.click(hit['x'],hit['y'])
   expect(page.locator('.viking-warrior').nth(hit['index'])).to_be_disabled()
   # A keyboard click also supports users who cannot use pointer targeting.
   warrior=page.locator('.viking-warrior').last
   warrior.focus();page.keyboard.press('Enter')
   expect(warrior).to_be_disabled()
   page.evaluate('location.hash="#appearance"')
   expect(page.locator('#appearance-view')).to_be_visible()
   for width in (390,320):
    page.set_viewport_size({'width':width,'height':950})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.screenshot(path=str(root/f'test-results/theme-viking-{width}.png'),full_page=True)
   page.emulate_media(reduced_motion='no-preference')
   page.locator('#theme-animation').uncheck();page.locator('#appearance-save').click()
   expect(page.locator('html')).to_have_attribute('data-animation','false')
   expect(page.locator('.viking-battle')).to_have_class('viking-battle is-paused')
   page.reload();expect(page.locator('#theme-animation')).not_to_be_checked()
   page.locator('[name=theme][value=fjord]').check();page.locator('#appearance-save').click()
   expect(page.locator('html')).to_have_attribute('data-theme','fjord')
   expect(page.locator('.viking-battle')).to_be_hidden()
   expect(page.locator('.goat-mountain')).to_be_visible()
   page.set_viewport_size({'width':1440,'height':1000})
   page.screenshot(path=str(root/'test-results/theme-fjord-desktop.png'),full_page=True)
   assert not errors, errors
   browser.close()
 finally:server.shutdown()
print('PASS persisted themes, static fallback, interactive actors, original goats, responsive settings')
