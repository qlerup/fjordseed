"""Search, paginate, stop and add through the existing policy dialog."""
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime
from torrent_search import ENGINES


class Demo(FakeRuntime):
    host_downloads = Path('/downloads')

    def __init__(self, state):
        super().__init__(state)
        self.rpc.side_effect = self.search_rpc
        self.running = True
        self.pattern = ''
        self.added = []
        self.installed = False
        self.install_polls = 0

    def status(self):
        return {**super().status(), 'ready': True, 'enabled': True}

    def search_rpc(self, action, data):
        if action == 'search-plugins':
            self.install_polls += 1
            names = list(ENGINES) if self.installed and self.install_polls > 2 else ['eztv'] if self.installed else []
            return {'plugins': [{'name': name, 'fullName': ENGINES[name], 'enabled': True} for name in names], 'catalog': ENGINES}
        if action == 'search-install':
            self.installed = True
            self.install_polls = 0
            return {'ok': True, 'requested': list(ENGINES) if data['name'] == 'all' else [data['name']]}
        if action == 'search-start':
            assert data['plugin'] == 'enabled'
            self.running = True
            self.pattern = data['pattern']
            return {'id': 123}
        if action == 'search-stop': self.running = False
        if action == 'search-results':
            if self.pattern == 'empty': return {'results': [], 'total': 0, 'status': 'Stopped'}
            if self.pattern == 'error': raise ValueError('Test: søgemaskinen er utilgængelig.')
            offset = data['offset']
            return {'results': [{'fileName': '<img src=x onerror=alert(1)> Ubuntu '+str(offset+i)+' '+('Long.title.'*12),
                                 'fileSize': 2147483648, 'nbSeeders': 15, 'nbLeechers': 2, 'engineName': 'Torrents.csv' if i % 2 else 'EZTV'}
                                for i in range(min(50, 51-offset))], 'total': 51,
                    'status': 'Running' if self.running else 'Stopped'}
        if action == 'search-resolve':
            return {'magnet': 'magnet:?xt=urn:btih:'+'a'*40, 'name': 'Ubuntu '+str(data['offset'])}
        if action == 'add': self.added.append(data)
        return {'ok': True}


with tempfile.TemporaryDirectory() as folder:
    app = create_app(folder, testing=True, runtime_factory=Demo)
    app.extensions['state'].save('a'*32, True)
    runtime = app.extensions['runtime']
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button', name='Log ind', exact=True).click()
            page.locator('.nav[href="#search"]').click()
            expect(page.locator('#search-view')).to_be_visible()
            expect(page.locator('#search-engines')).to_be_visible()
            page.locator('#search-install-all').click()
            expect(page.locator('#search-submit')).to_be_disabled()
            expect(page.locator('#search-status')).to_contain_text('Alle søgemaskiner er klar')
            expect(page.locator('#search-engine')).to_have_value('enabled')
            for label in ENGINES.values():
                expect(page.locator('#search-engine-status')).to_contain_text(label)
            page.locator('#search-engines-toggle').click()
            page.locator('#search-query').fill('Ubuntu')
            page.locator('#search-submit').click()
            expect(page.locator('.search-result')).to_have_count(50)
            expect(page.locator('.search-result').nth(0)).to_contain_text('EZTV')
            expect(page.locator('.search-result').nth(1)).to_contain_text('Torrents.csv')
            assert page.locator('#search-results img').count() == 0
            page.locator('#search-stop').click()
            expect(page.locator('#search-stop')).to_be_hidden()
            page.locator('#search-next').click()
            expect(page.locator('.search-result')).to_have_count(1)
            expect(page.locator('#search-page')).to_have_text('Side 2 af 2')
            page.locator('.search-result button').click()
            expect(page.locator('#ratio-dialog')).to_be_visible()
            expect(page.locator('#ratio-source')).to_have_text('Ubuntu 50')
            assert not runtime.added
            page.locator('#ratio-back').click()
            expect(page.locator('#add-dialog')).not_to_be_visible()
            page.locator('.search-result button').click()
            page.locator('#ratio-save').click()
            expect(page.locator('#ratio-dialog')).not_to_be_visible()
            assert len(runtime.added) == 1 and runtime.added[0]['magnet'].startswith('magnet:')
            page.locator('#search-prev').click()
            expect(page.locator('.search-result')).to_have_count(50)
            output = Path(__file__).resolve().parents[1]/'test-results'
            output.mkdir(exist_ok=True)
            for width, theme in [(w, t) for t in ('fjord', 'viking', 'nordic') for w in (1440, 390)]:
                page.set_viewport_size({'width': width, 'height': 1000})
                page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, theme)
                page.screenshot(path=str(output/f'torrent-search-{theme}-{width}.png'))
            page.locator('#search-query').fill('empty')
            page.locator('#search-submit').click()
            expect(page.locator('#search-status')).to_contain_text('Ingen resultater')
            page.locator('#search-query').fill('error')
            page.locator('#search-submit').click()
            expect(page.locator('#search-error')).to_contain_text('utilgængelig')
            assert not errors, errors
            browser.close()
            print('Search UI passed: desktop/mobile, themes, install, pagination, safe names, stop, policy dialog, add, empty/error.')
    finally:
        server.shutdown()
