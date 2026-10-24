"""UI-only regression checks: layouts, navigation, dialog motion and focus."""
from pathlib import Path
import sys,tempfile,threading,json,logging
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime
import green_credit as credit
logging.getLogger('werkzeug').setLevel(logging.ERROR)


class Demo(FakeRuntime):
    def status(self):
        feed=json.loads((self.state.root/'rss.json').read_text())[0]['id']
        torrents=[]
        for i,(name,progress,state) in enumerate([
            ('FreeBSD 14.3 · amd64 installation media',.73,'downloading'),
            ('Debian 13 · netinst amd64',1,'uploading'),
            ('Fedora Workstation · Live x86_64',.36,'downloading')]):
            torrents.append(dict(hash=str(i+1)*40,name=name,progress=progress,state=state,size=4*1024**3,
                uploaded=2*1024**3,downloaded=3*1024**3,dlspeed=12*1024**2 if progress<1 else 0,
                upspeed=2*1024**2,ratio=.7,seeding_time=1800,eta=420,
                ratio_limit=2,seeding_time_limit=-1,share_limit_action='Stop',
                tags='FjordSeed-RSS-'+feed if i==2 else ''))
        return {**super().status(),'enabled':True,'ready':True,'torrents_available':True,'torrents':torrents,
            'profiles':[{'id':'a'*32,'name':'FjordVPN · Danmark','desired':True,'relay_enabled':False}],
            'country':'DK','public_ip':'203.0.113.7','port':45001,'version':'5.2.4',
            'message':'qBittorrent kører gennem VPN.','transfer':{'dl_info_speed':24*1024**2,'up_info_speed':6*1024**2}}


with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);credit.CONFIG=root/'qbit';credit.POLICIES=root/'policy.json'
    app=create_app(root,testing=True,runtime_factory=Demo)
    app.extensions['state'].save('a'*32,True)
    app.extensions['rss'].save(dict(name='Alt Dansk TV',url='https://tracker.example/danish',enabled=True,ratio_limit=2))
    app.extensions['rss'].save(dict(name='Alt TV',url='https://tracker.example/world',enabled=True,ratio_limit=2))
    output=Path(__file__).resolve().parents[1]/'test-results/interface';output.mkdir(parents=True,exist_ok=True)
    server=make_server('127.0.0.1',0,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.route('**/api/storage/usage',lambda route:route.fulfill(json={'ok':True,'available':False}))
            page.route('**/api/storage',lambda route:route.fulfill(json={'ok':True,'path':'/media/library','selected':None,'pools':[]}))
            page.route('**/api/streaming',lambda route:route.fulfill(json={'ok':True,'enabled':False,'buffer':{},'storage':{},'folders':[]}))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.screenshot(path=str(output/'login.png'))
            page.locator('[name=username]').fill('admin');page.locator('[name=password]').fill((root/'initial-login.txt').read_text().strip())
            page.get_by_role('button',name='Log ind').click()
            expect(page.locator('#new-torrent')).to_be_enabled()
            for width in (1440,390):
                page.set_viewport_size({'width':width,'height':1000 if width==1440 else 844})
                for route in ('torrents','rss','connection','storage','streaming','trackers'):
                    page.locator('.nav[href="#'+route+'"]').click()
                    expect(page.locator('.nav[href="#'+route+'"]')).to_have_attribute('aria-current','page')
                    page.evaluate('scrollTo(0,0)')
                    page.screenshot(path=str(output/f'{route}-{width}.png'),full_page=True)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),route
                page.locator('.nav[href="#torrents"]').click()
                page.locator('#new-torrent').click();dialog=page.locator('#add-dialog')
                expect(dialog).to_be_visible()
                dialog.evaluate('async d=>{await Promise.allSettled(d.getAnimations().map(a=>a.finished));}')
                page.screenshot(path=str(output/f'add-{width}.png'))
                page.keyboard.press('Escape');expect(dialog).not_to_be_visible()
                expect(page.locator('#new-torrent')).to_be_focused()
                page.locator('.nav[href="#rss"]').click();page.locator('#rss-manage').click()
                expect(page.locator('#rss-feeds-dialog')).to_be_visible()
                page.locator('#rss-feeds-dialog').evaluate('async d=>{await Promise.allSettled(d.getAnimations().map(a=>a.finished));}')
                page.screenshot(path=str(output/f'feeds-{width}.png'))
                page.locator('#rss-feeds-dialog button.close').last.click()
                expect(page.locator('#rss-feeds-dialog')).not_to_be_visible()
            # Confirm native lifecycle remains synchronous, with CSS-only motion.
            page.locator('.nav[href="#torrents"]').click()
            motion=page.evaluate('''async()=>{const d=document.querySelector('#add-dialog');d.showModal();await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);const active=d.getAnimations().length>0;d.close();return {active,closedImmediately:!d.open};}''')
            assert motion['active'] and motion['closedImmediately'],motion
            page.emulate_media(reduced_motion='reduce')
            reduced=page.evaluate('''()=>{const d=document.querySelector('#add-dialog');d.showModal();const duration=getComputedStyle(d).transitionDuration;d.close();return duration;}''')
            assert all(float(v.strip().rstrip('s'))==0 for v in reduced.split(',')),reduced
            assert not errors,errors
            browser.close()
    finally:server.shutdown()
print('PASS six routes at desktop/mobile, login, nested feed modal, native motion, focus, reduced motion and no overflow')
