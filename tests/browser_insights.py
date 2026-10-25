"""Animated graph transitions and isolated account/seedbox series, using fixture measurements."""
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
    trackers.cache[ident]={'status':'ok','updated_at':now,'username':'Vikingen','stats':{'ratio':3.7,'uploaded':164*1024**3,'downloaded':41*1024**3,'buffer':371*1024**3,'seeding':23,'leeching':0,'seedbonus':2455.16,'hit_and_runs':0,'warnings':0,'seeding_size':123*1024**3,'total_uploads':0}}
    server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':1600,'height':1100})
            errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.clock.install()
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin');page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip());page.get_by_role('button',name='Log ind').click()
            card=page.locator('#tracker-insights');expect(card).to_be_visible();card.scroll_into_view_if_needed()
            expect(page.locator('#overview-view .tracker-card')).to_have_count(0)
            expect(card.locator('#insights-title')).to_have_text(CONFIG['name'])
            expect(card.locator('#insights-account-status')).to_contain_text('Vikingen')
            expect(card.locator('#insights-account-status')).to_contain_text('Forbundet')
            details=card.locator('#insights-account-details')
            expect(details.locator('.tracker-stats>div')).to_have_count(8)
            labels=details.locator('.tracker-stats>div>span').all_text_contents()
            assert not {'UPLOAD','DOWNLOAD','RATIO'}.intersection(labels)
            expect(details).to_contain_text('371,00 GiB')
            expect(details).to_contain_text('SHARDS')
            left=card.locator('.insights-account-details').bounding_box()
            right=card.locator('.insights-visual').bounding_box()
            assert left['x']+left['width']<=right['x']+1

            expect(card.locator('.insights-current svg')).to_be_visible()
            assert card.locator('.insights-current .insights-line').first.get_attribute('d').count('L')>1
            expect(card.locator('.insights-current .insights-change')).to_be_visible()
            expect(card.locator('.insights-current .insights-source')).not_to_contain_text('hele kontoen')
            chart=card.locator('.insights-current svg')
            chart.click()
            assert chart.evaluate('el=>getComputedStyle(el).outlineStyle')=='none'
            page.keyboard.press('Tab')
            page.keyboard.press('Shift+Tab')
            expect(chart).to_be_focused()
            assert chart.evaluate('el=>getComputedStyle(el).outlineStyle')=='solid'
            page.locator('#page-title').click()
            card.screenshot(path=str(output/'insights-desktop.png'))
            page.locator('.nav[href="#torrents"]').click()
            expect(card).to_be_hidden()
            expect(page.locator('#tracker-account-list')).to_have_count(0)
            expect(page.locator('#downloads-view')).to_be_visible()
            page.locator('.nav[href="#overview"]').click()
            expect(card).to_be_visible()
            card.scroll_into_view_if_needed()

            # Hover prevents automatic turns; leaving resumes, even after a mouse click.
            card.hover();expect(card).to_have_attribute('data-paused','true')
            page.clock.fast_forward(10000);expect(card).to_have_attribute('data-metric','ratio')
            page.mouse.move(0,0);expect(card).to_have_attribute('data-paused','false')
            page.clock.fast_forward(8050)
            expect(card.locator('.insights-stage')).to_have_class('insights-stage is-changing')
            assert card.locator('.insights-stage').evaluate('el=>getComputedStyle(el).transformStyle')=='flat'
            page.clock.fast_forward(1300)
            expect(card).to_have_attribute('data-metric','credited_uploaded')
            for key,label in [('real_uploaded','Reel upload'),('credited_downloaded','Kredit · download'),('real_downloaded','Reel download'),('ratio','Ratio')]:
                card.get_by_role('button',name=label,exact=True).click();page.clock.fast_forward(1300)
                expect(card).to_have_attribute('data-metric',key)
                expect(card.locator('.insights-current svg')).to_be_visible()
                if key.startswith('real_'):expect(card.locator('.insights-current .insights-source')).to_contain_text('Hele seedboxen')
            page.mouse.move(0,0);expect(card).to_have_attribute('data-paused','false')
            page.keyboard.press('Tab');expect(card).to_have_attribute('data-paused','true')
            expect(card.locator('[data-days]')).to_have_count(0)
            expect(card.locator('.insights-current svg')).to_be_visible()
            for width in (1024,650,390,320):
                page.set_viewport_size({'width':width,'height':1000});card.scroll_into_view_if_needed()
                assert card.evaluate('el=>el.scrollWidth<=el.clientWidth+1')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                if width<=1000:
                    left=card.locator('.insights-account-details').bounding_box()
                    right=card.locator('.insights-visual').bounding_box()
                    assert left['y']+left['height']<=right['y']+1

                if width==390:card.screenshot(path=str(output/'insights-mobile.png'))
            page.set_viewport_size({'width':1600,'height':1100})
            card.get_by_role('button',name='Alle',exact=True).click();page.clock.fast_forward(1300)
            expect(card).to_have_attribute('data-metric','all')
            expect(card.locator('.insights-current svg')).to_have_count(5)
            expect(card.locator('.insights-selector-value')).to_have_count(5)
            expect(card.locator('.insights-bottom')).to_have_count(0)
            colors=card.locator('.insights-current .insights-line').evaluate_all('els=>els.map(el=>getComputedStyle(el).stroke)')
            assert len(set(colors))==5
            card.screenshot(path=str(output/'insights-all-desktop.png'))
            for width in (650,390,320):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                if width==390:card.screenshot(path=str(output/'insights-all-mobile.png'))
            page.emulate_media(reduced_motion='reduce')
            card.get_by_role('button',name='Reel upload',exact=True).click()
            expect(card).to_have_attribute('data-metric','real_uploaded')
            assert not card.locator('.insights-stage.is-changing').count()
            expect(card).to_have_attribute('data-paused','true')
            # Absolute positive values; two changed observations fill only two slots.
            assert page.evaluate("""() => {
                const scene=trackerInsights,now=Date.now()/1000;
                const metric={key:'real_downloaded',name:'Download',color:'#fff'};
                const chart=scene.plot(metric,[{at:now-600,real_downloaded:928*1024**3},{at:now,real_downloaded:928*1024**3+1024**2}]);
                const coords=chart.querySelector('.insights-line').getAttribute('d').match(/[0-9.]+/g).map(Number);
                const last=Number(chart.querySelector('circle').getAttribute('cx'));
                const ticks=[...chart.querySelectorAll('.insights-y-tick')].map(el=>el.textContent);
                if(coords[0]<last*.97||coords[1]>=155||new Set(ticks).size!==3)return false;
                if(Math.abs(coords[1]-coords[3])<70)return false;
                if(!ticks.every(text=>text.includes('GiB')&&Math.abs(parseFloat(text.replace(',','.'))-928)<.01))return false;
                for(const value of [0,123,928*1024**3]){
                    const flat=scene.plot(metric,[{at:now-600,real_downloaded:value},{at:now,real_downloaded:value}]);
                    if(/NaN|Infinity/.test(flat.outerHTML))return false;
                    if(new Set([...flat.querySelectorAll('.insights-y-tick')].map(el=>el.textContent)).size!==3)return false;
                }

                const falling=scene.plot({key:'ratio',name:'Ratio',color:'#fff'},[{at:now-600,ratio:4},{at:now,ratio:3.9}]);
                if([...falling.querySelectorAll('.insights-y-tick')].some(el=>/[-\u2212]/.test(el.textContent)))return false;
                if(Number(falling.querySelector('circle').getAttribute('cy'))>=155)return false;
                const first=scene.plot(metric,[{at:now,real_downloaded:123}]);
                if(Number(first.querySelector('circle').getAttribute('cy'))>=155)return false;
                const gap=scene.plot(metric,[{at:now-600,real_downloaded:10},{at:now,real_downloaded:20,gap_before:true}]);
                return gap.querySelectorAll('.insights-line').length===2;
            }""")
            # A sparse or missing history is honest, not a synthetic trend line.
            page.route('**/api/trackers/*/history?*',lambda route:route.fulfill(json={'account':[],'seedbox':[],'days':30}))
            page.evaluate('trackerInsights.reload()')
            expect(card.locator('.insights-current .insights-empty')).to_contain_text('Din historik starter her')
            expect(card.locator('.insights-current svg')).to_have_count(0)
            page.unroute('**/api/trackers/*/history?*')
            page.route('**/api/trackers/*/history?*',lambda route:route.fulfill(status=503,json={'error':'Historik afventer'}))
            page.evaluate('trackerInsights.reload()')
            expect(card.locator('.insights-error')).to_have_text('Historik afventer')
            assert not errors,errors
            browser.close()
    finally:server.shutdown()
print('PASS five charts, ratio decline, source labels, automatic graph transition, hover pause/resume, responsive widths, reduced motion, empty/error states')
