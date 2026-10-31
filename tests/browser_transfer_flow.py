"""Real UI and canvas with synthetic rates; no Docker, trackers or downloads."""
from pathlib import Path
import sys
import tempfile
import threading
import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)

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
    app.extensions['runtime'].host_downloads=Path('/downloads')
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
            expect(page.locator('.nav[href="#overview"]')).to_have_attribute('aria-current','page')
            expect(page.locator('#downloads-view')).to_be_hidden()
            expect(page.locator('#download-queue')).to_be_hidden()
            for route in ('torrents','connection','storage','streaming','trackers'):
                if route=='torrents':page.locator('.nav[href="#torrents"]').click()
                else:
                    page.locator('.nav[href="#settings"]').click()
                    page.locator(f'#settings-tabs a[href="#{route}"]').click()
                expect(page.locator('#overview-view')).to_be_hidden()
                expect(flow).to_be_hidden()
                expect(page.locator('#new-torrent')).to_be_visible() if route=='torrents' else expect(page.locator('#new-torrent')).to_be_hidden()
                if route in ('torrents','rss'):expect(page.locator('#download-queue')).to_be_visible()
                if route=='connection':expect(page.locator('#settings-form')).to_be_visible()
            page.locator('.nav[href="#overview"]').click()
            page.reload()
            expect(page.locator('#overview-view')).to_be_visible()

            expect(flow).to_have_attribute('data-state','active')
            expect(page.locator('#flow-download-rate')).to_have_text('84 MB/s')
            expect(page.locator('#flow-upload-rate')).to_have_text('12 MB/s')
            expect(page.locator('#flow-vpn-icon img')).to_have_attribute('src','/static/flags/dk.svg')
            assert flow.bounding_box()['height'] < 350
            assert page.locator('.flow-rates').bounding_box()['x'] > page.locator('.flow-stage').bounding_box()['x'] + page.locator('.flow-stage').bounding_box()['width']
            page.wait_for_function('() => transferFlow && transferFlow.frame !== null && transferFlow.paths.length === 12')
            first=page.locator('.flow-canvas').evaluate('el=>el.toDataURL()')
            page.wait_for_function('(snapshot)=>document.querySelector(".flow-canvas").toDataURL()!==snapshot',arg=first)
            assert page.evaluate('transferFlow.paths.filter(p=>p.direction===0).every(p=>p.a.x>p.b.x)')
            assert page.evaluate('transferFlow.paths.filter(p=>p.direction===1).every(p=>p.a.x<p.b.x)')
            expect(page.locator('.flow-peers strong')).to_have_text('Peers')
            assert page.evaluate('transferFlow.paths.filter(p=>p.direction===1&&p.link===1).every(p=>p.b===transferFlow.points[3])')
            assert page.locator('[data-duck]').count()==0
            # Independent cadence, fixed per-packet speed, and complete delivery after stop.
            assert page.evaluate("""() => {
                const scene=transferFlow;
                const step=seconds=>{for(let t=0;t<seconds;t+=.05)scene.advance(.05);};
                step(8);
                const packets=[...scene.packets];
                if(packets.length<20 || packets.length>90)return false;
                if(new Set(packets.map(p=>p.speed)).size!==packets.length)return false;
                const waits=scene.lanes.map(l=>l.wait);
                if(new Set(waits).size!==6)return false;
                const positions=packets.map(p=>p.progress), speeds=packets.map(p=>p.speed);
                scene.update({ready:true,download:1,upload:1});
                if(packets.some((p,i)=>p.progress!==positions[i]||p.speed!==speeds[i]))return false;
                scene.resize();
                if(packets.some(p=>!scene.packets.includes(p)))return false;
                scene.update({ready:true,download:0,upload:1});
                scene.advance(.1);
                if(scene.packets.some(p=>p.direction===0&&!packets.includes(p)))return false;
                if(packets.some((p,i)=>Math.abs(p.progress-positions[i]-.1*speeds[i])>1e-9))return false;
                step(9);
                if(scene.packets.some(p=>p.direction===0)||!scene.packets.some(p=>p.direction===1))return false;
                const remaining=[...scene.packets];
                scene.update({ready:true,download:0,upload:0});
                // Stopping must preserve the visible particles and their brightness.
                if(remaining.some(p=>!scene.packets.includes(p)))return false;
                const original=scene.stroke, drawn=[];
                scene.stroke=(path,start,end,color,width)=>{if(width===1.5)drawn.push(end);};
                try {scene.draw(100);} finally {scene.stroke=original;}
                if(drawn.length!==remaining.length)return false;
                scene.advance(.1);
                if(scene.packets.some(p=>!remaining.includes(p)))return false;
                step(9);
                if(scene.packets.length)return false;
                scene.update({ready:true,download:84*1024**2,upload:12*1024**2});
                step(8);
                return scene.packets.some(p=>p.direction===0)&&scene.packets.some(p=>p.direction===1);
            }""")
            # Arrival at the VPN pulses once, even when a stopped transfer drains.
            assert page.evaluate("""() => {
                const scene=transferFlow,packets=scene.packets,rates=scene.rates;
                try {
                    scene.rates=[0,0];scene.packets=[{progress:.99,speed:.3,direction:0,strand:0,level:1}];
                    scene.advance(.1);
                    const pulse=scene.pulse;
                    if(!pulse||pulse.playState!=='running')return false;
                    scene.advance(.1);
                    if(scene.pulse!==pulse)return false;
                    scene.packets=[{progress:.99,speed:.3,direction:1,strand:0,level:1}];
                    scene.advance(.1);
                    return scene.pulse!==pulse&&pulse.playState==='idle';
                } finally {scene.packets=packets;scene.rates=rates;}
            }""")
            expect(flow.locator('.flow-rate-chart')).to_have_count(0)
            flow.screenshot(path=str(output/'transfer-flow-desktop.png'))
            for width in (390,320):
                page.set_viewport_size({'width':width,'height':1000})
                flow.scroll_into_view_if_needed()
                page.wait_for_function('() => Math.abs(transferFlow.width-document.querySelector(".flow-canvas").getBoundingClientRect().width)<1')
                assert flow.evaluate('el=>el.scrollWidth<=el.clientWidth')
                assert flow.bounding_box()['height'] < 500
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                for selector in ('#flow-download-rate','#flow-upload-rate','#flow-country'):
                    expect(page.locator(selector)).to_be_visible()
                if width==390: flow.screenshot(path=str(output/'transfer-flow-mobile.png'))
            # Reduced motion freezes both canvas and CSS, preserving real rates.
            page.emulate_media(reduced_motion='reduce')
            page.wait_for_function('() => transferFlow.frame === null')
            assert page.evaluate('transferFlow.pulse===null')
            page.evaluate('transferFlow.pulseShield()')
            assert page.evaluate('transferFlow.pulse===null')
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
            page.locator('.nav[href="#settings"]').click()
            page.locator('#settings-tabs a[href="#trackers"]').click()
            expect(flow).not_to_be_visible()
            page.wait_for_function('() => transferFlow.frame === null')
            page.locator('.nav[href="#overview"]').click()
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
