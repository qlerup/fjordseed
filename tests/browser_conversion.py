"""GPU preferences and manual/RSS selection without real downloads."""
from pathlib import Path,PurePosixPath
import sys,tempfile,threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

class Demo(FakeRuntime):
    host_downloads=PurePosixPath('/mnt/media')
    def status(self):return {**super().status(),'enabled':True,'ready':True}

with tempfile.TemporaryDirectory() as folder:
 app=create_app(folder,testing=True,runtime_factory=Demo)
 app.extensions['state'].save('',True)
 server=make_server('127.0.0.1',0,app,threaded=True)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 try:
  with sync_playwright() as p:
   browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
   errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.locator('[name=username]').fill('admin')
   page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
   page.get_by_role('button',name='Log ind',exact=True).click()
   page.locator('.nav[href="#settings"]').click()
   page.locator('#settings-tabs a[href="#conversion"]').click()
   expect(page.locator('#conversion-enabled')).not_to_be_checked()
   expect(page.locator('#conversion-bitrate')).to_have_value('30')
   assert page.locator('#conversion-bitrate option').evaluate_all('(options)=>options.map(o=>o.value)')==['20','30','40']
   for rate in ('20','30','40'):
    page.locator('#conversion-bitrate').select_option(rate)
    page.locator('#conversion-settings-save').click()
    expect(page.locator('#toast')).to_contain_text('gemt')
    page.reload()
    expect(page.locator('#conversion-bitrate')).to_have_value(rate)
   page.locator('#conversion-enabled').check()
   page.locator('#conversion-settings-save').click()
   expect(page.locator('#toast')).to_contain_text('gemt')
   page.reload();expect(page.locator('#conversion-enabled')).to_be_checked()
   assert page.locator('#conversion-server-address').count()==0
   expect(page.locator('#conversion-download-windows')).to_have_attribute('href','https://github.com/qlerup/fjordseed/releases/latest/download/Fjord-konvertering-Setup.exe')
   page.locator('#conversion-device-name').fill('Test-pc')
   page.locator('#conversion-device-create').click()
   expect(page.locator('#conversion-token-result')).to_be_visible()
   code=page.locator('#conversion-token-secret').input_value()
   import base64,json
   pairing=json.loads(base64.urlsafe_b64decode(code[5:]+'='*(-len(code[5:])%4)))
   assert pairing['server']==f'http://127.0.0.1:{server.server_port}' and pairing['token'].startswith('fsw_')
   expect(page.locator('#conversion-devices')).to_contain_text('Test-pc')
   for width in (1440,390,320):
    page.set_viewport_size({'width':width,'height':1000})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(Path(__file__).resolve().parents[1]/f'test-results/conversion-settings-{width}.png'),full_page=True)
   page.locator('.nav[href="#torrents"]').click();page.locator('#new-torrent').click()
   page.locator('#method-magnet').click();page.locator('#magnet').fill('magnet:?xt=urn:btih:'+'a'*40)
   page.locator('#add-save').click();expect(page.locator('#ratio-convert')).to_be_enabled()
   page.locator('#ratio-convert').check();expect(page.locator('#ratio-normal-seeding')).to_be_hidden()
   page.locator('#ratio-save').click();expect(page.locator('#ratio-dialog')).not_to_be_visible()
   assert app.extensions['runtime'].rpc.call_args.args[1]['convert'] is True
   page.locator('#new-torrent').click();page.locator('#method-rss').click()
   page.locator('#rss-name').fill('GPU-feed');page.locator('#rss-url').fill('https://example.test/rss')
   page.locator('#rss-next').click();page.locator('#rss-convert').check()
   expect(page.locator('#rss-normal-seeding')).to_be_hidden()
   page.locator('#rss-save').click();expect(page.locator('#add-dialog')).not_to_be_visible()
   feed=app.extensions['rss'].entries()[0];assert feed['convert'] is True
   page.evaluate('openRssForm('+__import__('json').dumps({**feed,'url':''})+')')
   page.locator('#rss-next').click();expect(page.locator('#rss-convert')).to_be_checked()
   page.screenshot(path=str(Path(__file__).resolve().parents[1]/'test-results/conversion-feed-mobile.png'))
   assert not errors,errors
   browser.close()
 finally:server.shutdown()
print('PASS conversion settings, manual/RSS create/edit, desktop/mobile, no JS errors')
