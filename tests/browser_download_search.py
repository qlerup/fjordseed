"""Search the full download inventory in every tab, including collapsed pages."""
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime


class Demo(FakeRuntime):
    host_downloads = Path('/downloads')

    def status(self):
        torrents = []
        for kind in ('manual', 'rss'):
            for i in range(12):
                name = 'Big.Brother.2013' if i == 0 else 'Nobody.2025' if i == 1 else f'Download {kind} {i}'
                torrents.append(dict(hash=f'{kind}-{i}', name=f'{name}.{kind}',
                    added_on=i, state='uploading' if i % 2 == 0 else 'stoppedUP',
                    progress=1, size=1024, dlspeed=0, upspeed=100 if i % 2 == 0 else 0,
                    tags='FjordSeed-RSS-test' if kind == 'rss' else ''))
        return {**super().status(), 'ready': True, 'enabled': True, 'torrents': torrents}


root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as folder:
    app = create_app(folder, testing=True, runtime_factory=Demo)
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
            page.locator('.nav[href="#torrents"]').click()
            search = page.get_by_role('searchbox', name='S\u00f8g i downloads')
            expect(page.locator('#torrent-list')).not_to_contain_text('Big.Brother')
            search.fill('BIG brother')
            expect(page.locator('#torrent-list .torrent')).to_have_count(2)
            expect(page.locator('#download-search-status')).to_contain_text('2 af 24')
            expect(page.locator('#manual-pagination')).to_be_hidden()
            expect(page.locator('#count')).to_have_text('24')
            search.fill('Nobody 2025')
            expect(page.locator('#manual-inactive')).to_have_attribute('open', '')
            expect(page.locator('#manual-inactive-list .torrent')).to_have_count(2)
            for tab, prefix in [('rss', 'rss'), ('manual', 'manual'), ('all', 'manual')]:
                page.locator(f'[data-download-filter={tab}]').click()
                expected = 2 if tab == 'all' else 1
                expect(page.locator(f'#{prefix}-inactive-list .torrent')).to_have_count(expected)
                expect(page.locator(f'#{prefix}-inactive-list')).to_be_visible()
                expect(search).to_have_value('Nobody 2025')
            page.evaluate('refresh()')
            expect(page.locator('#manual-inactive-list .torrent')).to_have_count(2)
            for width in (1440, 390, 320):
                page.set_viewport_size({'width': width, 'height': 1000})
                search.focus()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(root/'test-results'/f'download-search-{width}.png'), full_page=True)
            search.fill('no-such-download')
            expect(page.locator('#download-search-status')).to_have_text('Ingen downloads matcher din s\u00f8gning.')
            expect(page.locator('#empty')).to_be_hidden()
            expect(page.locator('#manual-inactive')).to_be_hidden()
            page.locator('#download-search-clear').click()
            expect(search).to_be_focused()
            expect(search).to_have_value('')
            expect(page.locator('#download-search-status')).to_be_hidden()
            expect(page.locator('#torrent-list .torrent')).to_have_count(5)
            expect(page.locator('#manual-inactive')).not_to_have_attribute('open', '')
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
print('PASS full-inventory search, all/RSS/manual tabs, inactive matches, refresh, clearing and mobile')
