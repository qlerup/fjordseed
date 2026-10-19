"""Streaming navigation, saved mode, connection and errors without real downloads."""
from pathlib import Path,PurePosixPath
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from app import create_app
from streaming import Streaming
from test_app import FakeRuntime

with tempfile.TemporaryDirectory() as directory:
    app=create_app(directory,testing=True,runtime_factory=FakeRuntime)
    app.extensions['runtime'].host_downloads=PurePosixPath('/mnt/media/Film')
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            for width in (390,1440):
                page=browser.new_page(viewport={'width':width,'height':1000});errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}/')
                page.locator('[name=username]').fill('admin')
                page.locator('[name=password]').fill((Path(directory)/'initial-login.txt').read_text().strip())
                page.get_by_role('button',name='Log ind').click()
                page.locator('.nav[href="#streaming"]').click()
                expect(page.locator('#streaming-view')).to_be_visible()
                expect(page.locator('#downloads-view')).not_to_be_visible()
                expect(page.locator('#page-title')).to_have_text('Streaming')
                expect(page.locator('#streaming-enabled')).to_be_checked()
                expect(page.locator('#streaming-buffer')).to_be_checked()
                expect(page.locator('#streaming-buffer')).to_be_disabled()
                page.locator('#streaming-move-retained').check()
                page.locator('#streaming-enabled').uncheck()
                expect(page.locator('#streaming-move-retained')).to_be_disabled()
                expect(page.locator('#streaming-buffer')).to_be_enabled()
                page.locator('#streaming-buffer').check()
                page.locator('#streaming-save').click()
                page.reload()
                expect(page.locator('#streaming-enabled')).not_to_be_checked()
                expect(page.locator('#streaming-buffer')).to_be_checked()
                expect(page.locator('#streaming-move-retained')).to_be_checked()
                page.locator('#streaming-enabled').check()
                expect(page.locator('#streaming-buffer')).to_be_disabled()
                page.locator('#streaming-enabled').uncheck()
                expect(page.locator('#streaming-buffer')).to_be_checked()
                page.locator('#streaming-buffer').uncheck()
                page.locator('#streaming-save').click()
                expect(page.locator('#streaming-mode')).to_contain_text('Fra:')
                page.reload()
                expect(page.locator('#streaming-enabled')).not_to_be_checked()
                page.locator('.nav[href="#storage"]').click()
                expect(page.locator('#storage-buffer')).to_contain_text('direkte download')
                page.locator('.nav[href="#streaming"]').click()
                page.route('**/api/streaming/flix',lambda route:route.fulfill(json={'ok':True,'choices':[
                    {'id':'a'*32,'path':'/mnt/media/Film','library_path':'/library/server/media/Film','current':True}]}))
                page.locator('#streaming-find').click()
                expect(page.locator('#streaming-folders')).to_be_visible()
                page.route('**/api/streaming/connect',lambda route:route.fulfill(json={'ok':True,'enabled':True,
                    'connected':True,'host_path':'/mnt/media/Film','library_path':'/library/server/media/Film'}))
                page.locator('#streaming-connect').click()
                expect(page.locator('#streaming-buffer')).to_be_checked()
                expect(page.locator('#streaming-buffer')).to_be_disabled()
                expect(page.locator('#streaming-link-status')).to_contain_text('Forbundet mappe:')
                (Path(__file__).resolve().parents[1]/'test-results').mkdir(exist_ok=True)
                page.screenshot(path=str(Path(__file__).resolve().parents[1]/'test-results'/f'streaming-{width}.png'),full_page=True)
                page.unroute('**/api/streaming/flix')
                page.route('**/api/streaming/flix',lambda route:route.fulfill(status=400,json={'error':'Start FjordFlix'}))
                page.locator('#streaming-find').click()
                expect(page.locator('#streaming-error')).to_contain_text('Start FjordFlix')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert not errors,errors
                app.extensions['state'].get()
                Streaming(app.extensions['runtime']).save(True)
                print('PASS streaming navigation, toggle, reload, connection and errors',width)
                page.close()
            browser.close()
    finally:server.shutdown()
