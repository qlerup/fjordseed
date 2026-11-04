"""Title/cover previews for file, magnet and batch flows in all themes."""
import base64
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
    def status(self): return {**super().status(), 'ready': True, 'enabled': True}


with tempfile.TemporaryDirectory() as folder:
    app = create_app(folder, testing=True, runtime_factory=Demo)
    poster = 'https://image.tmdb.org/t/p/w185/example.jpg'
    ident = 'a'*64
    (app.extensions['covers'].root/(ident+'.img')).write_bytes(base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5V8AAAAASUVORK5CYII='))
    cover_calls = 0
    def cover(source):
        global cover_calls
        if not source: return None
        cover_calls += 1
        return None if cover_calls == 1 else '/api/covers/'+ident
    app.extensions['covers'].request = cover
    def benefits(meta, selected):
        if 'No cover' in meta.get('name', ''): return {'status': 'unknown', 'matches': []}
        return {'status': 'matched', 'matches': [{'tracker_name': 'Fixture',
            'title': 'The Actual Film (2026) '+('Long release title '*8), 'poster': poster,
            'seeders': 7 if meta.get('name','').startswith('Second') else 0}]}
    app.extensions['trackers'].benefits.request = benefits
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1100})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button', name='Log ind', exact=True).click()
            for theme in ('fjord', 'viking', 'nordic'):
                page.goto(f'http://127.0.0.1:{server.server_port}/#appearance')
                page.locator(f'[name=theme][value={theme}]').check()
                page.locator('#appearance-save').click()
                expect(page.locator('html')).to_have_attribute('data-theme', theme)
                page.goto(f'http://127.0.0.1:{server.server_port}/#torrents')
                page.locator('#new-torrent').click()
                page.locator('#torrent-file').set_input_files({'name': 'NordicBytes-171773.torrent',
                    'mimeType': 'application/x-bittorrent', 'buffer': b'd4:infod6:lengthi1e4:name15:Actual.Film.mkvee'})
                page.locator('#add-save').click()
                expect(page.locator('#ratio-identity .torrent-identity-title')).to_contain_text('The Actual Film (2026)')
                expect(page.locator('#ratio-source')).to_have_text('NordicBytes-171773.torrent')
                expect(page.locator('#preview-benefits .seeders-warning')).to_contain_text('0 seeders')
                expect(page.locator('#ratio-save')).to_be_enabled()
                expect(page.locator('#ratio-identity img')).to_be_visible()
                assert page.locator('#ratio-identity img').evaluate('img=>img.complete&&img.naturalWidth>0')
                for width in (1440, 390):
                    page.set_viewport_size({'width': width, 'height': 1100})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert page.locator('#ratio-dialog').evaluate('el=>el.scrollWidth<=el.clientWidth')
                    page.screenshot(path=str(Path(__file__).resolve().parents[1]/'test-results'/f'torrent-preview-{theme}-{width}.png'))
                page.locator('#ratio-dialog .close').click()
                page.locator('#new-torrent').click()
                page.locator('#method-magnet').click()
                page.locator('#magnet').fill('magnet:?xt=urn:btih:'+'b'*40+'&dn=No%20cover%20Film')
                page.locator('#add-save').click()
                expect(page.locator('#ratio-identity .torrent-identity-title')).to_have_text('No cover Film')
                expect(page.locator('#ratio-identity .torrent-identity-cover')).to_have_text('Intet cover')
                expect(page.locator('#ratio-identity img')).to_have_count(0)
                expect(page.locator('#preview-benefits .seeders-warning')).to_have_count(0)
                page.locator('#ratio-dialog .close').click()
                page.locator('#new-torrent').click()
                page.locator('#torrent-file').set_input_files([
                    {'name': 'First.torrent', 'mimeType': 'application/x-bittorrent',
                     'buffer': b'd4:infod6:lengthi1e4:name15:Actual.Film.mkvee'},
                    {'name': 'Second.torrent', 'mimeType': 'application/x-bittorrent',
                     'buffer': b'd4:infod6:lengthi1e4:name15:Second.Film.mkvee'}])
                page.locator('#add-save').click()
                expect(page.locator('.torrent-batch-item .torrent-identity-title')).to_have_count(2)
                expect(page.locator('.torrent-batch-item .torrent-identity-cover img')).to_have_count(2)
                expect(page.locator('#ratio-identity')).to_be_hidden()
                expect(page.locator('.torrent-batch-item .torrent-identity-title').first).to_contain_text('The Actual Film')
                expect(page.locator('.torrent-batch-item .seeders-warning')).to_have_count(1)
                expect(page.locator('.torrent-batch-item').nth(1)).to_contain_text('7 seeders')
                expect(page.locator('#ratio-save')).to_be_enabled()
                page.locator('#ratio-dialog .close').click()
            assert not app.extensions['runtime'].rpc.called
            assert not errors, errors
            browser.close()
            print('PASS torrent title and async cover, filename, missing cover, batch, mobile/desktop in Fjord/Viking/Nordic.')
    finally:
        server.shutdown()
