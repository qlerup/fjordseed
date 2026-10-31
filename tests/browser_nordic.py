"""Opt-in theme, persisted motion, existing controls and responsive visual review.

Uses an isolated local app and simulated torrents; never touches a live seedbox.
"""
from pathlib import Path
import logging
import sys
import tempfile
import threading
import math
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime
from test_trackers import CONFIG


class Demo(FakeRuntime):
    empty = False

    def status(self):
        torrents = [
            dict(hash='a'*40, name='Northern landscapes · A journey through the fjords · 2160p',
                 cover='/api/covers/'+'a'*64,
                 state='downloading', progress=.64, size=18*1024**3, dlspeed=12*1024**2,
                 upspeed=2*1024**2, ratio=.42),
            dict(hash='b'*40, name='The quiet coast · Season 01 · Complete collection',
                 state='uploading', progress=1, size=9*1024**3, dlspeed=0,
                 upspeed=4*1024**2, ratio=2.41, tags='FjordSeed-RSS-demo'),
        ]
        return {**super().status(), 'ready':True, 'enabled':True,
                'torrents':[] if self.empty else torrents,
                'transfer':{'dl_info_speed':12*1024**2,'up_info_speed':6*1024**2}}


root = Path(__file__).resolve().parents[1]
logging.getLogger('werkzeug').setLevel(logging.ERROR)
with tempfile.TemporaryDirectory() as folder:
    app = create_app(folder, testing=True, runtime_factory=Demo)
    app.extensions['runtime'].host_downloads = Path('/downloads')
    trackers = app.extensions['trackers']
    ident = trackers.save(CONFIG)
    now = time.time()
    for i in range(72):
        at = now-(71-i)*600
        trackers.history.record(ident, {'ratio':3.7+math.sin(i/10)*.2,'seedbonus':2400+i*.2,
            'credited_uploaded':(145+i*.067)*1024**3,'credited_downloaded':(35+i*.023)*1024**3}, at)
        trackers.history.record('seedbox', {'real_uploaded':(210+i*.1)*1024**3,'real_downloaded':(430+i*.05)*1024**3}, at)
    trackers.cache[ident] = {'status':'ok','updated_at':now,'username':'Vikingen','stats':{
        'ratio':3.7,'uploaded':164*1024**3,'downloaded':41*1024**3,'buffer':371*1024**3,
        'seeding':23,'leeching':0,'seedbonus':2455.16,'hit_and_runs':0,'warnings':0,
        'seeding_size':123*1024**3,'total_uploads':0}}
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width':1440,'height':1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/streaming', lambda route:route.fulfill(json={'conversion_enabled':False}))
            page.route('**/api/covers/'+'a'*64,lambda route:route.fulfill(content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="96"><rect width="64" height="96" fill="#294b59"/><path d="M0 70 30 20 64 70" fill="#b3ccd2"/><text x="32" y="87" text-anchor="middle" fill="white" font-size="9">FJORD</text></svg>'))
            def status_with_cover(route):
                response=route.fetch()
                data=response.json()
                if data.get('torrents'):
                    data['torrents'][0]['cover']='/api/covers/'+'a'*64
                route.fulfill(response=response,json=data)
            page.route('**/api/status',status_with_cover)
            page.route('**/api/conversion/dolby-vision', lambda route:route.fulfill(json={'items':[]}))
            page.route('**/api/storage', lambda route:route.fulfill(json={'path':'/downloads','buffer':'/downloads/.incomplete','fjordflix_enabled':False,'streaming_enabled':True}))
            page.route('**/api/storage/usage', lambda route:route.fulfill(json={'path':'/downloads','total_bytes':2*1024**4,'used_bytes':.7*1024**4,'free_bytes':1.3*1024**4}))
            page.route('**/api/storage/temporary-usage', lambda route:route.fulfill(json={'path':'/downloads','current_rss_bytes':128*1024**3,'release_schedule':{'count':0,'available':True,'timeline':[]}}))
            base = f'http://127.0.0.1:{server.server_port}'
            page.goto(base)
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button', name='Log ind', exact=True).click()
            page.goto(base+'/#appearance')
            expect(page.locator('html')).to_have_attribute('data-theme','fjord')
            expect(page.locator('#system-themes [name=theme]')).to_have_count(2)
            expect(page.locator('#system-themes [value=fjord]')).to_be_visible()
            expect(page.locator('#system-themes [value=nordic]')).to_be_visible()
            expect(page.locator('#animated-themes [name=theme]')).to_have_count(1)
            expect(page.locator('#animated-themes [value=viking]')).to_be_visible()
            page.locator('[name=theme][value=nordic]').check()
            page.locator('#appearance-save').click()
            expect(page.locator('#appearance-status')).to_contain_text('Nordisk er gemt')
            page.reload()
            expect(page.locator('html')).to_have_attribute('data-theme','nordic')
            expect(page.locator('[name=theme][value=nordic]')).to_be_checked()
            expect(page.locator('.goat-mountain')).to_be_hidden()
            expect(page.locator('.viking-battle')).to_be_hidden()
            expect(page.locator('.ambient-particles')).to_be_hidden()
            # Ensure the real background loads, rather than a silent CSS fallback.
            assert page.evaluate('''async () => {
                const image = new Image(); image.src='/static/nordic-saga-fjord-clear.png';
                await image.decode(); return image.naturalWidth > 1000;
            }''')
            glow = page.locator('.ambient-glow').first
            assert glow.evaluate('e=>getComputedStyle(e).animationName') == 'nordic-mist'
            page.locator('#theme-animation').uncheck()
            page.locator('#appearance-save').click()
            expect(page.locator('html')).to_have_attribute('data-animation','false')
            assert glow.evaluate('e=>getComputedStyle(e).animationPlayState') == 'paused'
            page.reload()
            expect(page.locator('#theme-animation')).not_to_be_checked()
            page.locator('#theme-animation').check()
            page.locator('#appearance-save').click()
            expect(page.locator('html')).to_have_attribute('data-animation','true')
            page.emulate_media(reduced_motion='reduce')
            assert glow.evaluate('e=>getComputedStyle(e).animationName') == 'none'
            assert page.locator('aside').evaluate('e=>getComputedStyle(e).animationName') == 'none'
            page.emulate_media(reduced_motion='no-preference')
            # The second sign is the original navigation, with keyboard and
            # toggle behavior; it does not duplicate links or change routes.
            trigger=page.locator('.nav[href="#settings"]')
            expect(trigger).to_have_attribute('aria-expanded','true')
            trigger.click(force=True)
            expect(page.locator('#settings-tabs')).to_be_hidden()
            expect(page.locator('#appearance-view')).to_be_visible()
            expect(trigger).to_have_attribute('aria-expanded','false')
            trigger.click(force=True)
            expect(page.locator('#settings-tabs')).to_be_visible()
            # Inspect the physical release, including its folded wooden back.
            hanger=page.locator('.settings-sign-hanger')
            assert hanger.evaluate('''e=>{
                const a=e.getAnimations().find(a=>a.animationName==='nordic-sign-release');
                if(!a)return false;a.pause();a.currentTime=0;
                return new DOMMatrix(getComputedStyle(e).transform).m22<0
                    && getComputedStyle(e).opacity==='1';
            }''')
            for at in (0,350,675,1350):
                hanger.evaluate('(e,t)=>{e.getAnimations()[0].currentTime=t}',at)
                page.screenshot(path=str(root/f'test-results/nordic-sign-release-{at}.png'),clip=page.locator('.navigation-signs').bounding_box())
            hanger.evaluate('e=>e.getAnimations()[0].finish()')
            trigger.press('Escape')
            expect(page.locator('#settings-tabs')).to_be_hidden()
            expect(trigger).to_be_focused()
            trigger.click(force=True)
            hanger.evaluate('async e=>Promise.all(e.getAnimations().map(a=>a.finished.catch(()=>{})))')
            page.locator('#settings-tabs a[href="#connection"]').click(force=True)
            expect(page.locator('#connection')).to_be_visible()
            for width in (1920,1440,900,390,320):
                page.set_viewport_size({'width':width,'height':1000})
                page.goto(base+'/#overview')
                expect(page.locator('#tracker-insights')).to_be_visible()
                expect(page.locator('.insights-current svg')).to_be_visible()
                nav=page.locator('.navigation-signs')
                assert nav.evaluate('e=>getComputedStyle(e).animationName') == ('nordic-sign-sway' if width>800 else 'none')
                if width>800:
                    # The sign intentionally keeps moving while hovered.
                    box=nav.bounding_box()
                    assert box['width'] < 950
                    assert abs(box['x']+box['width']/2-width/2) < 8
                    page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2)
                    assert nav.evaluate('e=>getComputedStyle(e).animationPlayState') == 'running'
                    traffic=page.locator('#traffic-flow').bounding_box()
                    assert traffic['y']+traffic['height'] <= page.locator('#tracker-overview').bounding_box()['y']
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), ('overview',width)
                page.screenshot(path=str(root/f'test-results/nordic-overview-{width}.png'),full_page=True,animations='allow')
                page.goto(base+'/#appearance')
                expect(page.locator('#appearance-view')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), ('appearance',width)
                page.locator('.settings-sign-hanger').evaluate('async e=>Promise.all(e.getAnimations().map(a=>a.finished.catch(()=>{})))')
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(root/f'test-results/nordic-appearance-{width}.png'),full_page=True)
                # Skip Playwright's stationary-element wait for the swaying sign.
                page.locator('.nav[href="#torrents"]').click(force=True)
                expect(page.locator('.nav.active')).to_have_count(1)
                expect(page.locator('.nav[href="#torrents"]')).to_have_attribute('aria-current','page')
                expect(page.locator('#torrent-list')).to_contain_text('Northern landscapes')
                expect(page.locator('#torrent-list .torrent-cover').first).to_be_visible()
                poster=page.locator('#torrent-list .torrent-cover').first.bounding_box()
                if width>800:
                    assert poster['width']>=120 and poster['height']>=180
                else:
                    title=page.locator('#torrent-list .torrent-head').first.bounding_box()
                    assert poster['y']+poster['height']<=title['y']+1
                if width>1100:
                    toolbar=page.locator('#download-toolbar').bounding_box()
                    worklist=page.locator('#downloads-view').bounding_box()
                    assert 0 <= worklist['y']-(toolbar['y']+toolbar['height']) <= 24
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), ('downloads',width)
                page.screenshot(path=str(root/f'test-results/nordic-downloads-{width}.png'),full_page=True,animations='allow')
                page.locator('[data-download-filter=manual]').click()
                expect(page.locator('#torrent-list')).not_to_contain_text('The quiet coast')
                page.locator('[data-download-filter=all]').click()
                page.locator('#new-torrent').click()
                expect(page.locator('#add-dialog')).to_be_visible()
                assert glow.evaluate('e=>getComputedStyle(e).animationPlayState') == 'paused'
                page.locator('#method-magnet').click()
                page.locator('#magnet').fill('invalid')
                page.locator('#add-save').click()
                expect(page.locator('#add-error')).to_be_visible()
                assert page.locator('#add-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth'), ('dialog',width)
                page.screenshot(path=str(root/f'test-results/nordic-dialog-{width}.png'))
                page.locator('#add-dialog>.dialog-heading .close').click()
                page.locator('[data-torrent-toggle-control=details]').first.click()
                expect(page.locator('.torrent-extra').first).to_be_visible()
                page.screenshot(path=str(root/f'test-results/nordic-details-{width}.png'),full_page=True,animations='allow')
                page.locator('[data-torrent-toggle-control=details]').first.click()
                page.get_by_role('button',name='Ratio Northern landscapes',exact=False).click()
                expect(page.locator('#edit-ratio-dialog')).to_be_visible()
                page.screenshot(path=str(root/f'test-results/nordic-ratio-{width}.png'),animations='allow')
                page.locator('#edit-ratio-dialog .close').first.click()
                # View every settings tab, including long-form converter controls.
                for tab,view in [('connection','#connection'),('storage','#storage-view'),
                                 ('trackers','#trackers-view'),('conversion','#conversion-view'),('streaming','#streaming-view')]:
                    page.goto(base+'/#'+tab)
                    expect(page.locator(view)).to_be_visible()
                    page.locator('.settings-sign-hanger').evaluate('async e=>Promise.all(e.getAnimations().map(a=>a.finished.catch(()=>{})))')
                    menu=page.locator('#settings-tabs').bounding_box()
                    sign=page.locator('aside').bounding_box()
                    assert menu['y'] >= sign['y']+sign['height']-12
                    assert menu['y']+menu['height'] <= page.locator(view).bounding_box()['y']
                    assert page.locator('#settings-tabs').evaluate('e=>e.parentElement.className') == 'settings-sign-hanger'
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (tab,width)
                    if width in (1440,390):
                        page.screenshot(path=str(root/f'test-results/nordic-{tab}-{width}.png'),full_page=True,animations='allow')
            page.set_viewport_size({'width':1440,'height':1000})
            page.goto(base+'/#overview')
            expect(page.locator('.insights-current svg')).to_be_visible()
            page.get_by_role('button',name='Reel upload',exact=True).click()
            expect(page.locator('.insights-stage')).to_have_class('insights-stage is-changing')
            expect(page.locator('#tracker-insights')).to_have_attribute('data-metric','real_uploaded')
            # The new harbour is animated independently from the old node diagram.
            assert page.evaluate("""() => {
                const scene=transferFlow, before=JSON.stringify(scene.rates);
                scene.draw(1);const first=scene.canvas.toDataURL();
                scene.draw(4);const next=scene.canvas.toDataURL();
                const ready=scene.ready;scene.ready=false;
                scene.draw(1);const idle=scene.canvas.toDataURL();
                scene.draw(4);const idleNext=scene.canvas.toDataURL();scene.ready=ready;
                return first!==next && idle===idleNext && JSON.stringify(scene.rates)===before;
            }""")
            assert 'nordic-saga-fjord-clear.png' in page.locator('.ambient-scene').evaluate('e=>getComputedStyle(e).backgroundImage')
            # The VPN landmark has no inherited breathing animation, halo or
            # arrival pulse, even while both streams are active.
            assert page.locator('.flow-core-shell').evaluate("e=>e.getAnimations({subtree:true}).length") == 0
            assert page.locator('.flow-core-shell').evaluate("e=>getComputedStyle(e,'::before').animationName") == 'none'
            assert page.locator('.flow-equalizer').first.evaluate('e=>getComputedStyle(e).display') == 'none'
            page.goto(base+'/#torrents')
            expect(page.locator('#torrent-list .nordic-voyage')).to_have_count(2)
            expect(page.locator('#torrent-list .nordic-voyage-lane[data-moving=true]')).to_have_count(3)
            # Ten fixed-color wear patterns; selection survives status rebuilds.
            assert page.evaluate('''async ()=>{
                const variants=Array.from({length:100},(_,i)=>torrentBannerVariant({hash:'fixture-'+i}));
                if(new Set(variants).size!==10)return false;
                const t={hash:'a'.repeat(40),name:'Stable banner',state:'downloading',progress:.5};
                if(card(t).dataset.banner!==card({...t,dlspeed:1000}).dataset.banner)return false;
                const sources=await Promise.all(Array.from({length:10},async(_,i)=>{
                    const path='/static/nordic-banners/banner-'+String(i+1).padStart(2,'0')+'.svg';
                    const response=await fetch(path);if(!response.ok)throw Error(path);
                    const text=await response.text(),image=new Image();image.src=path;await image.decode();return text;
                }));
                return new Set(sources).size===10;
            }''')
            # Review the ten silhouettes with identical content and color.
            page.evaluate('''()=>{
                const catalog=document.createElement('section');catalog.id='banner-catalog';
                catalog.style.cssText='padding:24px;background:#081823;max-width:1200px';
                for(let i=1;i<=10;i++){
                    const row=document.querySelector('#torrent-list .torrent').cloneNode(true);
                    row.dataset.banner=String(i);row.querySelector('.torrent-name').textContent='Sejldugsbanner '+String(i).padStart(2,'0');
                    catalog.append(row);
                }
                document.querySelector('main').append(catalog);
            }''')
            page.locator('#banner-catalog').screenshot(path=str(root/'test-results/nordic-banner-variants.png'))
            page.locator('#banner-catalog').evaluate('e=>e.remove()')
            for direction in ('download','upload'):
                ship=page.locator(f'#torrent-list .nordic-voyage-lane[data-direction={direction}][data-moving=true] .nordic-voyage-ship').first
                assert ship.evaluate('e=>getComputedStyle(e).animationName') == ('nordic-cargo-in' if direction=='download' else 'nordic-cargo-out')
            page.evaluate("document.documentElement.dataset.animation='false';document.dispatchEvent(new Event('fjordseed:appearance'))")
            assert page.locator('.nordic-voyage-ship').first.evaluate('e=>getComputedStyle(e).animationName')=='none'
            page.evaluate("document.documentElement.dataset.animation='true';document.dispatchEvent(new Event('fjordseed:appearance'))")
            page.emulate_media(reduced_motion='reduce')
            assert page.locator('.nordic-voyage-ship').first.evaluate('e=>getComputedStyle(e).animationName')=='none'
            page.emulate_media(reduced_motion='no-preference')
            app.extensions['runtime'].empty = True
            page.goto(base+'/#torrents')
            page.reload()
            expect(page.locator('#empty')).to_be_visible()
            page.screenshot(path=str(root/'test-results/nordic-empty.png'),full_page=True)
            page.goto(base+'/#appearance')
            # An error keeps the current theme and leaves controls usable for retry.
            page.route('**/api/appearance',lambda route:route.fulfill(status=500,json={'error':'Test: kunne ikke gemme'}))
            page.locator('[name=theme][value=fjord]').check()
            page.locator('#appearance-save').click()
            expect(page.locator('#appearance-error')).to_have_text('Test: kunne ikke gemme')
            expect(page.locator('html')).to_have_attribute('data-theme','nordic')
            expect(page.locator('#appearance-save')).to_be_enabled()
            page.unroute('**/api/appearance')
            page.locator('#appearance-save').click()
            expect(page.locator('html')).to_have_attribute('data-theme','fjord')
            assert page.locator('#settings-tabs').evaluate('e=>e.parentElement.tagName') == 'MAIN'
            assert page.locator('#settings-tabs').count() == 1
            expect(page.locator('.nav[href="#settings"]')).not_to_have_attribute('aria-expanded','true')
            expect(page.locator('.goat-mountain')).to_be_visible()
            assert page.locator('aside').evaluate('e=>getComputedStyle(e).position') == 'fixed'
            page.locator('[name=theme][value=viking]').check()
            page.locator('#appearance-save').click()
            expect(page.locator('.viking-battle')).to_be_visible()
            expect(page.locator('.goat-mountain')).to_be_hidden()
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
print('PASS Nordisk persistence, motion, theme switching, charts, errors and existing controls at 1920/1440/900/390/320px')
