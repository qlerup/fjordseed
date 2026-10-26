"""Exercise library selection, queueing and badges without changing real media."""
import logging
from pathlib import Path, PurePosixPath
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

logging.getLogger('werkzeug').setLevel(logging.ERROR)


class Demo(FakeRuntime):
    host_downloads = PurePosixPath('/mnt/media')

    def __init__(self, state):
        super().__init__(state)
        self.items = [
            dict(id='a'*64, name='Movie/Film <2026>.mkv', size=66*1024**3, converted=None, eligible=True, reason=''),
            dict(id='b'*64, name='Already converted/Film.mkv', size=20*1024**3,
                 converted=dict(bitrate=30, converted_at=1793030400), eligible=False, reason='Allerede konverteret'),
            dict(id='c'*64, name='Unmanaged.mkv', size=1024**3, converted=None, eligible=False, reason='Ingen torrent')]
        self.jobs = []
        self.rpc.side_effect = self.reply

    def status(self):
        return {**super().status(), 'enabled': True, 'ready': True}

    def reply(self, action, data):
        if action == 'library-list':
            return dict(items=self.items, jobs=self.jobs, truncated=False)
        if action == 'library-convert':
            assert data == dict(id='a'*64, bitrate=40)
            self.items[0]['eligible'] = False
            self.jobs = [dict(id='d'*32, name=self.items[0]['name'], bitrate=40, phase='queued', state='queued', detail='Venter på pc')]
            return self.jobs[0]
        if action == 'library-cancel':
            self.jobs = []
            self.items[0]['eligible'] = True
        return {'ok': True}


with tempfile.TemporaryDirectory() as folder:
    app = create_app(folder, testing=True, runtime_factory=Demo)
    app.extensions['state'].save('', True)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport=dict(width=1440, height=1000))
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button', name='Log ind', exact=True).click()
            page.goto(f'http://127.0.0.1:{server.server_port}/#conversion')
            films = page.locator('#library-conversion-list .library-film')
            expect(films).to_have_count(3)
            expect(films.filter(has_text='Already converted').locator('.library-converted')).to_contain_text('30 Mbps')
            expect(films.filter(has_text='Unmanaged').get_by_role('button')).to_be_disabled()
            page.evaluate("() => window.addEventListener('workspace-find',event=>window.found=event.detail)")
            films.filter(has_text='Movie/Film').get_by_role('button').click()
            assert page.evaluate('found')=='Film <2026>.mkv'
            expect(page.locator('#library-conversion-jobs')).to_be_empty()
            for width in (1440, 390, 320):
                page.set_viewport_size(dict(width=width, height=1000))
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(Path(__file__).resolve().parents[1]/f'test-results/library-conversion-{width}.png'), full_page=True)
            page.locator('#library-conversion-search').fill('Already')
            expect(films).to_have_count(1)
            assert not errors, errors
            browser.close()
        print('PASS library list, shared PC lookup, flags, search, desktop/mobile and no JS errors')
    finally:
        server.shutdown()
