"""Real cube transitions and isolated account/seedbox series, using fixture measurements."""
from pathlib import Path
import math, sys, tempfile, threading, time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime
from test_trackers import CONFIG

root=Path(__file__).resolve().parents[1];output=root/'test-results';output.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as folder:
    app=create_app(folder,testing=True,runtime_factory=FakeRuntime)
    trackers=app.extensions['trackers'];ident=trackers.save(CONFIG)
    now=time.time()
    for i in range(288):
        at=now-(287-i)*600
        trackers.history.record(ident,{'ratio':4.1+math.sin(i/48)*.3-i*.00065,'credited_uploaded':(145+i*.067)*1024**3,'credited_downloaded':(35+i*.023)*1024**3},at)
        trackers.history.record('seedbox',{'real_uploaded':(210+i*.1)*1024**3,'real_downloaded':(430+i*.05)*1024**3},at)
    trackers.cache[ident]={'status':'ok','updated_at':now,'username':'Vikingen','stats':{'ratio':3.7,'uploaded':164*1024**3,'downloaded':41*1024**3}}
    server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':1600,'height':1100})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.clock.install()
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin');page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip());page.get_by_role('button',name='Log ind').click()
            card=page.locator('#tracker-insights');expect(card).to_be_visible();card.scroll_into_view_if_needed()
            expect(card.locator('.insights-current svg')).to_be_visible()
            assert card.locator('.insights-current .insights-line').first.get_attribute('d').count('L')>1
            expect(card.locator('.insights-current .insights-change')).to_contain_text('↘')
            expect(card.locator('.insights-current .insights-source')).to_contain_text('hele kontoen')
            card.screenshot(path=str(output/'insights-desktop.png'))
            page.locator('.nav[href="#torrents"]').click()
            expect(card).to_be_hidden()
            expect(page.locator('#tracker-account-list')).to_be_hidden()
            expect(page.locator('#downloads-view')).to_be_visible()
            page.locator('.nav[href="#overview"]').click()
            expect(card).to_be_visible()
            card.scroll_into_view_if_needed()

            # Hover prevents automatic turns; leaving resumes, even after a mouse click.
            card.hover();expect(card).to_have_attribute('data-paused','true')
            page.clock.fast_forward(10000);expect(card).to_have_attribute('data-metric','ratio')
            page.mouse.move(0,0);expect(card).to_have_attribute('data-paused','false')
            page.clock.fast_forward(8050)
            expect(card.locator('.insights-cube')).to_have_class('insights-cube is-turning')
            assert card.locator('.insights-cube').evaluate('el=>getComputedStyle(el).transformStyle')=='preserve-3d'
            page.clock.fast_forward(1300)
            expect(card).to_have_attribute('data-metric','credited_uploaded')
            for key,label in [('real_uploaded','Reel upload'),('credited_downloaded','Kredit · download'),('real_downloaded','Reel download'),('ratio','Ratio')]:
                card.get_by_role('button',name=label,exact=True).click();page.clock.fast_forward(1300)
                expect(card).to_have_attribute('data-metric',key)
                expect(card.locator('.insights-current svg')).to_be_visible()
                if key.startswith('real_'):expect(card.locator('.insights-current .insights-source')).to_contain_text('Hele seedboxen')
            page.mouse.move(0,0);expect(card).to_have_attribute('data-paused','false')
            page.keyboard.press('Tab');expect(card).to_have_attribute('data-paused','true')
            card.get_by_role('button',name='24 t.',exact=True).click()
            expect(card.locator('.insights-current svg')).to_be_visible()
            for width in (1024,650,390,320):
                page.set_viewport_size({'width':width,'height':1000});card.scroll_into_view_if_needed()
                assert card.evaluate('el=>el.scrollWidth<=el.clientWidth+1')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                if width==390:card.screenshot(path=str(output/'insights-mobile.png'))
            page.emulate_media(reduced_motion='reduce')
            card.get_by_role('button',name='Reel upload',exact=True).click()
            expect(card).to_have_attribute('data-metric','real_uploaded')
            assert not card.locator('.insights-cube.is-turning').count()
            expect(card).to_have_attribute('data-paused','true')
            # A sparse or missing history is honest, not a synthetic trend line.
            page.route('**/api/trackers/*/history?*',lambda route:route.fulfill(json={'account':[],'seedbox':[],'days':30}))
            card.get_by_role('button',name='30 dage',exact=True).click()
            expect(card.locator('.insights-current .insights-empty')).to_contain_text('Din historik starter her')
            expect(card.locator('.insights-current svg')).to_have_count(0)
            page.unroute('**/api/trackers/*/history?*')
            page.route('**/api/trackers/*/history?*',lambda route:route.fulfill(status=503,json={'error':'Historik afventer'}))
            card.get_by_role('button',name='7 dage',exact=True).click()
            expect(card.locator('.insights-error')).to_have_text('Historik afventer')
            assert not errors,errors
            browser.close()
    finally:server.shutdown()
print('PASS five charts, ratio decline, source labels, automatic cube turn, hover pause/resume, responsive widths, reduced motion, empty/error states')
