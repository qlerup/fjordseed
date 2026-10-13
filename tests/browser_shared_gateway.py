"""Both VPN choices at desktop/mobile widths; no Docker or real torrents."""
import sys,tempfile,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime


class Demo(FakeRuntime):
    def status(self):
        result=super().status()
        result['profiles']=[{'id':'a'*32,'name':'Seedbox','desired':True,'relay_enabled':False},
            {'id':'b'*32,'name':'Gateway','desired':True,'relay_enabled':True,'gateway_enabled':True},
            {'id':'c'*32,'name':'Legacy TCP','desired':True,'relay_enabled':True}]
        if self.state.get()['enabled']:
            shared=self.state.get()['profile_id']=='b'*32
            result.update(ready=True,port=57000 if shared else 38850,public_ip='185.111.109.2',country='DK',
                torrent_mode='gateway' if shared else 'dedicated',
                message='qBittorrent deler gatewayens VPN med sin egen åbne torrentport.' if shared else 'qBittorrent kører gennem VPN.')
        return result


root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as folder:
    app=create_app(folder,testing=True,runtime_factory=Demo)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button',name='Log ind').click()
            page.locator('.nav[href="#connection"]').click()
            assert page.locator('#profile option[value="'+('c'*32)+'"]').evaluate('option=>option.disabled')
            page.locator('#profile').select_option('a'*32);page.locator('#connect').click()
            expect(page.locator('#public-address')).to_contain_text(':38850')
            expect(page.locator('#public-address')).not_to_contain_text('Delt gateway-VPN')
            page.locator('#profile').select_option('b'*32);page.locator('#connect').click()
            expect(page.locator('#public-address')).to_contain_text(':57000 · Delt gateway-VPN · Åben torrentport')
            expect(page.locator('#vpn-message')).to_contain_text('sin egen åbne torrentport')
            page.reload();expect(page.locator('#profile')).to_have_value('b'*32)
            output=root/'test-results';output.mkdir(exist_ok=True)
            for width,height in [(1440,1000),(390,844)]:
                page.set_viewport_size({'width':width,'height':height})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(output/f'shared-gateway-{width}.png'),full_page=True)
            page.locator('#stop').click();expect(page.locator('#new-torrent')).to_be_disabled()
            page.locator('#profile').select_option('a'*32);page.locator('#connect').click()
            expect(page.locator('#public-address')).to_contain_text(':38850')
            expect(page.locator('#public-address')).not_to_contain_text('Delt gateway-VPN')
            assert not errors,errors
            browser.close()
    finally:server.shutdown()
print('PASS: dedicated/shared gateway choice, public torrent port, persistence, stop, desktop/mobile; legacy TCP blocked.')
