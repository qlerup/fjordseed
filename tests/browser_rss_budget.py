"""Desktop/mobile storage budget editing, status and persistence; no downloads."""
import logging
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime


def run():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        app=create_app(root,testing=True,runtime_factory=FakeRuntime)
        server=make_server('127.0.0.1',0,app,threaded=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch()
                try:
                    for width in (1440,390):
                        page=browser.new_page(viewport={'width':width,'height':1000});errors=[]
                        page.route('**/api/storage/temporary-usage',lambda route:route.fulfill(json={'temporary_bytes':700*1024**3,'rss_temporary_bytes':700*1024**3}))
                        page.route('**/api/streaming',lambda route:route.fulfill(json={'enabled':False}))
                        page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(f'http://127.0.0.1:{server.server_port}')
                        page.locator('[name=username]').fill('admin')
                        page.locator('[name=password]').fill((root/'initial-login.txt').read_text().strip())
                        page.get_by_role('button',name='Log ind').click()
                        page.locator('.nav[href="#torrents"]').click()
                        page.locator('#downloads-manage-feeds').click()
                        expect(page.locator('#rss-storage-limit')).to_be_visible()
                        page.locator('#rss-storage-limit').fill('1.5')
                        page.locator('#rss-storage-unit').select_option('TB')
                        page.locator('#rss-storage-save').click()
                        expect(page.locator('#rss-storage-badge')).to_have_text('Afventer måling')
                        assert app.extensions['rss'].storage_limit()['limit_bytes']==int(1.5*1024**4)
                        page.evaluate('refreshRss()')
                        expect(page.locator('#rss-storage-limit')).to_have_value('1.5')
                        # Polling must never overwrite an unsaved edit.
                        page.locator('#rss-storage-limit').fill('750')
                        page.locator('#rss-storage-unit').select_option('GB')
                        page.evaluate('refreshRss()')
                        expect(page.locator('#rss-storage-limit')).to_have_value('750')
                        page.locator('#rss-storage-save').click()
                        expect(page.locator('#rss-storage-save')).to_be_enabled()
                        assert app.extensions['rss'].storage_limit()['limit_bytes']==750*1024**3
                        page.evaluate("renderRssBudget({limit_bytes:750*1024**3,temporary_bytes:700*1024**3,reserved_bytes:50*1024**3,committed_bytes:750*1024**3,resume_bytes:675*1024**3,paused:true,reason:'limit'})")
                        expect(page.locator('#rss-storage-badge')).to_have_text('RSS på lagerpause')
                        expect(page.locator('#rss-storage-status')).to_contain_text('reserveret')
                        page.locator('#rss-storage-limit').fill('0')
                        page.locator('#rss-storage-save').click()
                        assert page.locator('#rss-storage-limit').evaluate('e=>!e.validity.valid')
                        page.locator('#rss-storage-limit').fill('750')
                        shot=Path(__file__).resolve().parents[1]/'test-results'/f'rss-budget-{width}.png'
                        shot.parent.mkdir(exist_ok=True)
                        page.locator('#rss-storage-heading').scroll_into_view_if_needed()
                        page.screenshot(path=str(shot))
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        controls=page.locator('.rss-storage-controls')
                        assert controls.evaluate('e=>e.scrollWidth<=e.clientWidth')
                        page.locator('#rss-storage-limit').fill('')
                        page.locator('#rss-storage-save').click()
                        expect(page.locator('#rss-storage-badge')).to_have_text('Ingen grænse')
                        assert app.extensions['rss'].storage_limit()['limit_bytes'] is None
                        assert not errors,errors
                        page.close()
                finally:browser.close()
        finally:server.shutdown();thread.join(timeout=5);server.server_close()
    print('Desktop/mobile RSS budget controls, units, validation, persistence, polling and pause status passed.')


if __name__=='__main__':run()
