"""Nordic village journeys: direction, cargo, traffic lifecycle and responsive UI."""
from pathlib import Path
import logging
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime


class JourneyRuntime(FakeRuntime):
    def status(self):
        return {**super().status(), 'ready': True, 'enabled': True, 'country': 'DK', 'torrents': [],
                'transfer': {'dl_info_speed': 8 * 1024**2, 'up_info_speed': 2 * 1024**2}}


root = Path(__file__).resolve().parents[1]
logging.getLogger('werkzeug').setLevel(logging.ERROR)
with tempfile.TemporaryDirectory() as folder:
    app = create_app(folder, testing=True, runtime_factory=JourneyRuntime)
    app.extensions['runtime'].host_downloads = Path('/downloads')
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1050})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder) / 'initial-login.txt').read_text().strip())
            page.get_by_role('button', name='Log ind', exact=True).click()
            page.goto(f'http://127.0.0.1:{server.server_port}/#appearance')
            page.locator('[name=theme][value=nordic]').check()
            page.locator('#appearance-save').click()
            expect(page.locator('html')).to_have_attribute('data-theme', 'nordic')
            page.goto(f'http://127.0.0.1:{server.server_port}/#overview')
            expect(page.locator('#traffic-flow')).to_be_visible()
            assert page.evaluate('''() => {
                const scene=new FjordNordicCaravan();
                const cargo=Array.from({length:100},(_,i)=>scene.loot(i));
                if(cargo.filter(c=>c==='gold').length!==70)return false;
                if(cargo.filter(c=>c==='captive').length!==30)return false;
                scene.advance(0,[1,1],true);
                const party=scene.parties[1], id=party.id;
                party.progress=.99;scene.advance(.24,[1,1],true);
                if(party.progress<=1||party.id!==id)return false;
                const a=scene.position({direction:0,progress:0},1000,500);
                const b=scene.position({direction:0,progress:1},1000,500);
                const d=scene.position({direction:0,progress:1.9999},1000,500);
                const u=scene.position({direction:1,progress:0},1000,500);
                const v=scene.position({direction:1,progress:1.9999},1000,500);
                if(!(a.x>b.x&&b.x>d.x&&u.x<v.x&&a.y<v.y))return false;
                const before=scene.serial.join();scene.advance(.5,[0,0],true);
                if(scene.serial.join()!==before)return false;
                scene.advance(0,[0,0],false);
                if(scene.parties.length)return false;
                for(let i=0;i<1500;i++)scene.advance(.1,[1,1],true);
                return scene.parties.length<20;
            }''')
            for width in (1920, 1440, 900, 390, 320):
                page.set_viewport_size({'width': width, 'height': 1050})
                page.evaluate('''() => {
                    transferFlow.update({ready:true,download:8388608,upload:2097152});
                    transferFlow.caravan.parties=[
                        {direction:0,progress:.35,id:0,cargo:'gold'},
                        {direction:0,progress:.75,id:1,cargo:'gold'},
                        {direction:0,progress:1.25,id:2,cargo:'captive'},
                        {direction:0,progress:1.7,id:3,cargo:'gold'},
                        {direction:1,progress:.25,id:4,cargo:'gold'},
                        {direction:1,progress:.7,id:5,cargo:'captive'},
                        {direction:1,progress:1.25,id:6,cargo:'gold'},
                        {direction:1,progress:1.7,id:8,cargo:'captive'}];
                    transferFlow.resize();transferFlow.draw(4);
                }''')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
                assert page.locator('.flow-stage').bounding_box()['height'] == (430 if width <= 600 else 390)
                for label in ('.flow-computer>strong', '.flow-tracker>strong', '.flow-peers>strong', '#flow-vpn-label'):
                    expect(page.locator(label)).to_be_visible()
                page.locator('#traffic-flow').screenshot(path=str(root / f'test-results/nordic-caravan-{width}.png'))
            assert page.evaluate('''() => {
                const s=transferFlow;s.draw(1);const before=s.canvas.toDataURL();
                s.caravan.advance(.5,s.rates,s.ready);s.draw(1.5);
                return before!==s.canvas.toDataURL();
            }''')
            # Frozen scenes remain stable; ordinary status polls preserve journeys.
            page.evaluate("document.documentElement.dataset.animation='false';document.dispatchEvent(new Event('fjordseed:appearance'))")
            assert page.evaluate('''() => {
                const s=transferFlow,party=s.caravan.parties[0],progress=party.progress;
                s.update({ready:true,download:1024,upload:512});
                if(!s.caravan.parties.includes(party)||party.progress!==progress)return false;
                s.draw(1);const a=s.canvas.toDataURL();s.draw(4);
                return a===s.canvas.toDataURL()&&s.frame===null;
            }''')
            page.emulate_media(reduced_motion='reduce')
            page.evaluate("document.documentElement.dataset.animation='true';document.dispatchEvent(new Event('fjordseed:appearance'))")
            assert page.evaluate('transferFlow.frame===null')
            page.evaluate('transferFlow.update({ready:false,download:999,upload:999})')
            assert page.evaluate('transferFlow.caravan.parties.length===0&&transferFlow.rates.every(n=>n===0)')
            page.evaluate("document.documentElement.dataset.theme='fjord';document.dispatchEvent(new Event('fjordseed:appearance'))")
            assert page.locator('.flow-computer .flow-icon').is_visible()
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
print('PASS village routes, 70/30 cargo, VPN crossing, bounded parties, traffic lifecycle, motion preferences and 320–1920px layouts')
