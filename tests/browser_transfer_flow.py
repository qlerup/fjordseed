"""Real UI and canvas with synthetic rates; no Docker, trackers or downloads."""
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

class Demo(FakeRuntime):
    def status(self):
        return {**super().status(),'enabled':True,'ready':True,'country':'DK',
                'transfer':{'dl_info_speed':84*1024**2,'up_info_speed':12*1024**2}}

root=Path(__file__).resolve().parents[1]
output=root/'test-results'
output.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as folder:
    app=create_app(folder,testing=True,runtime_factory=Demo)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={'width':1768,'height':1080})
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button',name='Log ind').click()
            flow=page.locator('#traffic-flow')
            expect(flow).to_have_attribute('data-state','active')
            expect(page.locator('#flow-download-rate')).to_have_text('84 MB/s')
            expect(page.locator('#flow-upload-rate')).to_have_text('12 MB/s')
            expect(page.locator('#flow-vpn-icon img')).to_have_attribute('src','/static/flags/dk.svg')
            page.wait_for_function('() => transferFlow && transferFlow.frame !== null && transferFlow.paths.length === 12')
            first=page.locator('.flow-canvas').evaluate('el=>el.toDataURL()')
            page.wait_for_function('(snapshot)=>document.querySelector(".flow-canvas").toDataURL()!==snapshot',arg=first)
            assert page.evaluate('transferFlow.point(transferFlow.paths[0],0).x < transferFlow.point(transferFlow.paths[0],1).x')
            assert page.locator('[data-duck]').count()==0
            flow.screenshot(path=str(output/'transfer-flow-desktop.png'))
            for width in (390,320):
                page.set_viewport_size({'width':width,'height':1000})
                flow.scroll_into_view_if_needed()
                page.wait_for_function('() => Math.abs(transferFlow.width-document.querySelector(".flow-canvas").getBoundingClientRect().width)<1')
                assert flow.evaluate('el=>el.scrollWidth<=el.clientWidth')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                for selector in ('#flow-download-rate','#flow-upload-rate','#flow-country'):
                    expect(page.locator(selector)).to_be_visible()
                if width==390: flow.screenshot(path=str(output/'transfer-flow-mobile.png'))
            # Reduced motion freezes both canvas and CSS, preserving real rates.
            page.emulate_media(reduced_motion='reduce')
            page.wait_for_function('() => transferFlow.frame === null')
            assert page.locator('.flow-orbit-one').evaluate('el=>getComputedStyle(el).animationName')=='none'
            frozen=page.locator('.flow-canvas').evaluate('el=>el.toDataURL()')
            page.evaluate('transferFlow.draw(performance.now()/1000+10)')
            assert frozen==page.locator('.flow-canvas').evaluate('el=>el.toDataURL()')
            page.emulate_media(reduced_motion='no-preference')
            page.wait_for_function('() => transferFlow.frame !== null')
            # UI polls must retain one scene and one bounded set of paths.
            assert page.evaluate('''() => {const scene=transferFlow; for(let i=0;i<15;i++)renderFlow(current); return scene===transferFlow&&transferFlow.paths.length===12;}''')
            # Stop the normal network poll for deterministic synthetic states.
            page.route('**/api/status',lambda route:route.fulfill(json={**app.extensions['runtime'].status(),
                'transfer':{'dl_info_speed':0,'up_info_speed':0}}))
            page.evaluate('refresh()')
            expect(flow).to_have_attribute('data-traffic','idle')
            assert page.evaluate('transferFlow.rates.every(rate=>rate===0)')
            expect(page.locator('#flow-note')).to_contain_text('Ingen download eller upload')
            page.set_viewport_size({'width':1440,'height':1000})
            flow.screenshot(path=str(output/'transfer-flow-idle.png'))
            page.locator('.nav[href="#trackers"]').click()
            expect(flow).not_to_be_visible()
            page.wait_for_function('() => transferFlow.frame === null')
            page.locator('.nav[href="#torrents"]').click()
            page.wait_for_function('() => transferFlow.frame !== null')
            page.route('**/api/status',lambda route:route.fulfill(status=503,json={'error':'Fixture unavailable'}))
            page.evaluate('refresh()')
            expect(flow).to_have_attribute('data-state','blocked')
            assert page.evaluate('transferFlow.frame===null && transferFlow.rates.every(rate=>rate===0)')
            expect(page.locator('#flow-download-rate')).to_have_text('—')
            expect(page.locator('#flow-status')).to_have_text('Status utilgængelig')
            expect(page.locator('#flow-vpn-label')).to_have_text('VPN afventer')
            flow.screenshot(path=str(output/'transfer-flow-blocked.png'))
            assert not errors,errors
            browser.close()
    finally:
        server.shutdown()
print('PASS: live canvas, directions, rates, country, mobile 320/390px, reduced motion, refresh reuse, idle, hidden scene and status failure.')
