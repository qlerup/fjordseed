"""Decorative canvas: real UI, motion, reduced motion and input isolation."""
import logging,sys,tempfile,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime
logging.getLogger('werkzeug').setLevel(logging.ERROR)
with tempfile.TemporaryDirectory() as folder:
    app=create_app(folder,testing=True,runtime_factory=FakeRuntime)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    out=Path(__file__).resolve().parents[1]/'test-results/hologram';out.mkdir(exist_ok=True)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.route('**/api/storage',lambda r:r.fulfill(json={'ok':True,'path':'/downloads','selected':None,'pools':[]}))
            page.route('**/api/storage/usage',lambda r:r.fulfill(json={'ok':True,'available':False}))
            page.route('**/api/streaming',lambda r:r.fulfill(json={'ok':True,'enabled':False,'buffer':{},'storage':{},'folders':[]}))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button',name='Log ind').click()
            canvas=page.locator('#skull-hologram');expect(canvas).to_have_attribute('aria-hidden','true')
            page.wait_for_function('document.querySelector("#skull-hologram")?.width===Math.round(innerWidth*Math.min(devicePixelRatio,1.5))')
            assert canvas.evaluate('e=>getComputedStyle(e).pointerEvents')=='none'
            before=canvas.evaluate('e=>e.toDataURL()');page.wait_for_timeout(250)
            assert canvas.evaluate('e=>e.toDataURL()')!=before
            for width in (1440,390):
                page.set_viewport_size({'width':width,'height':1000 if width==1440 else 844})
                for route in ('torrents','rss','connection','storage','streaming','trackers'):
                    page.locator('.nav[href="#'+route+'"]').click()
                    expect(page.locator('.nav[href="#'+route+'"]')).to_have_attribute('aria-current','page')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.locator('.nav[href="#rss"]').click()
                expect(page.locator('#rss-view')).to_be_visible()
                page.screenshot(path=str(out/f'rss-{width}.png'),full_page=True)
                page.locator('#rss-new').click();expect(page.locator('#rss-dialog')).to_be_visible()
                page.locator('#rss-name').fill('Hologram input check')
                page.keyboard.press('Escape');expect(page.locator('#rss-dialog')).not_to_be_visible()
            page.emulate_media(reduced_motion='reduce');page.wait_for_timeout(100)
            still=canvas.evaluate('e=>e.toDataURL()');page.wait_for_timeout(250)
            assert canvas.evaluate('e=>e.toDataURL()')==still
            assert not errors,errors
            browser.close()
    finally:server.shutdown()
print('PASS hologram animation, reduced motion, six routes, desktop/mobile, modal input and no overflow/errors')
