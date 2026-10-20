"""Isolated feed-size UI test; never starts Docker, a VPN or a download."""
import logging, sys, tempfile, threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime


def run():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    with tempfile.TemporaryDirectory() as folder:
        app=create_app(Path(folder),testing=True,runtime_factory=FakeRuntime)
        server=make_server('127.0.0.1',0,app,threaded=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch()
                try:
                    for width in (1440,390):
                        page=browser.new_page(viewport={'width':width,'height':900});errors=[]
                        page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(f'http://127.0.0.1:{server.server_port}')
                        page.locator('[name=username]').fill('admin')
                        page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
                        page.get_by_role('button',name='Log ind').click()
                        page.locator('.nav[href="#rss"]').click();page.locator('#rss-new').click()
                        name='Size '+str(width)
                        page.locator('#rss-name').fill(name);page.locator('#rss-url').fill(f'https://tracker.example/rss?fixture={width}')
                        page.locator('#rss-start-trigger').click()
                        page.get_by_role('option',name='Alle poster i feedet',exact=True).click()
                        page.locator('#rss-max-size').fill('0');page.locator('#rss-next').click()
                        expect(page.locator('#rss-source-step')).to_be_visible()
                        page.locator('#rss-max-size').fill('1.5');page.locator('#rss-size-unit').select_option('GB')
                        for unit in ('MB','GB','TB'):
                            page.locator('#rss-size-unit').select_option(unit)
                            assert page.evaluate('rssMaxSize()')==int(1.5*1024**({'MB':2,'GB':3,'TB':4}[unit]))
                        page.locator('#rss-size-unit').select_option('GB')
                        box=page.locator('.rss-size-fields').bounding_box()
                        assert box['x']>=0 and box['x']+box['width']<=width
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        screenshot=Path(__file__).resolve().parents[1]/'test-results'/f'rss-size-{width}.png'
                        screenshot.parent.mkdir(exist_ok=True);page.screenshot(path=str(screenshot))
                        page.locator('#rss-next').click();page.locator('#rss-save').click()
                        expect(page.locator('#rss-dialog')).not_to_be_visible()
                        page.locator('#rss-manage').click()
                        card=page.locator('.rss-feed-card').filter(has=page.get_by_text(name,exact=True))
                        card.get_by_role('button',name='Rediger',exact=True).click()
                        expect(page.locator('#rss-max-size')).to_have_value('1.5')
                        expect(page.locator('#rss-size-unit')).to_have_value('GB')
                        page.locator('#rss-max-size').fill('');page.locator('#rss-next').click();page.locator('#rss-save').click()
                        expect(page.locator('#rss-dialog')).not_to_be_visible()
                        saved=next(e for e in app.extensions['rss'].entries() if e['name']==name)
                        assert saved['max_size_bytes'] is None
                        assert not errors,errors
                        page.close()
                finally:browser.close()
        finally:server.shutdown();thread.join(timeout=5);server.server_close()
    print('Desktop/mobile RSS size controls, units, save/edit/clear and validation passed.')


if __name__=='__main__':run()
