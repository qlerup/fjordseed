"""Isolated UI test: fake runtime, no Docker or downloads."""
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
        result=super().status()
        result['profiles']=[{'id':'a'*32,'name':'Seedbox VPN','desired':True,'relay_enabled':False}]
        if self.state.get()['enabled']:
            result.update(ready=True,message='VPN klar',public_ip='203.0.113.5',country='France',port=45001,version='5.2.1',
                torrents=[{'hash':'b'*40,'name':'Test Linux ISO','progress':.42,'size':1234567890,'dlspeed':2000000,'upspeed':15000,'ratio':.1,'state':'downloading'}])
        return result


root=Path(__file__).resolve().parents[1]
(root/'test-results').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as folder:
    app=create_app(folder,testing=True,runtime_factory=Demo)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button',name='Log ind').click()
            expect(page.locator('#new-torrent')).to_be_disabled()
            page.locator('#profile').select_option('a'*32)
            page.locator('#connect').click()
            expect(page.locator('#new-torrent')).to_be_enabled()
            expect(page.locator('#public-address')).to_contain_text('Frankrig')
            page.locator('#new-torrent').click()
            page.locator('#magnet').fill('magnet:?xt=urn:btih:'+'b'*40)
            page.locator('#add-save').click()
            expect(page.locator('#add-dialog')).not_to_be_visible()
            assert app.extensions['runtime'].rpc.call_args.args[0]=='add'
            page.get_by_role('button',name='Pause Test Linux ISO').click()
            page.get_by_role('button',name='Fjern Test Linux ISO').click()
            expect(page.get_by_text('Downloadede filer bevares.',exact=False)).to_be_visible()
            page.locator('#delete-dialog .close').click()
            assert page.locator('.country-location img').first.evaluate('(img)=>img.complete && img.naturalWidth>0')
            page.screenshot(path=str(root/'test-results/desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(root/'test-results/mobile.png'),full_page=True)
            page.locator('#stop').click()
            expect(page.locator('#new-torrent')).to_be_disabled()
            assert not errors,errors
            browser.close()
    finally:server.shutdown()
print('PASS: desktop/mobile, login, VPN selection, torrent actions, disabled without VPN')
