"""Real Chromium extension + isolated FjordSeed. No tracker or torrent network traffic."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading

from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from test_app import FakeRuntime


class ReadyRuntime(FakeRuntime):
    def status(self):
        return dict(super().status(), ready=True, enabled=True, message='Test VPN klar')


root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as folder:
    work = Path(folder)
    app = create_app(work/'app', testing=True, runtime_factory=ReadyRuntime)
    app.extensions['state'].save('a'*32, True)
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f'http://127.0.0.1:{server.server_port}/'
    extension = work/'extension'
    shutil.copytree(root/'chrome-extension', extension)
    manifest = json.loads((extension/'manifest.json').read_text(encoding='utf-8'))
    # Only test fixture grants localhost up front; shipped extension requests the user's host.
    manifest['host_permissions'].append('http://127.0.0.1/*')
    (extension/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with (extension/'background.js').open('a', encoding='utf-8') as script:
        script.write('\nself.fixtureBegin = begin;\n')
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(str(work/'chrome'), channel='chromium', headless=True,
                args=[f'--disable-extensions-except={extension}', f'--load-extension={extension}'])
            context.route('**/*', lambda route: route.continue_() if
                route.request.url.startswith((address, 'chrome-extension://')) else route.abort())
            worker = context.service_workers[0] if context.service_workers else context.wait_for_event('serviceworker')
            worker.evaluate('url => chrome.storage.local.set({seedUrl:url})', address)
            # Mock ONLY the extension's network call, not the real FjordSeed UI/API handoff.
            worker.evaluate('''() => {
              self.fetches = 0;
              self.fetch = async (url, options) => {
                if (url !== 'https://nordicbytes.org/torrents/download/42') throw Error('Unexpected external request');
                if (options.credentials !== 'include' || options.redirect !== 'error') throw Error('Unsafe request');
                self.fetches++;
                return new Response('d4:infod6:lengthi1e4:name7:fixture12:piece lengthi16384e6:pieces20:aaaaaaaaaaaaaaaaaaaaee',
                  {headers:{'Content-Type':'application/x-bittorrent'}});
              };
            }''')
            with context.expect_page() as opened:
                worker.evaluate("() => self.fixtureBegin('https://nordicbytes.org/torrents/download/42')")
            page = opened.value
            page.wait_for_url('**/login')
            # A second click cannot replace a pending torrent or fetch it again.
            assert 'allerede' in worker.evaluate("async () => {try {await self.fixtureBegin('https://nordicbytes.org/torrents/download/42')} catch(e) {return e.message}}")
            assert worker.evaluate('self.fetches') == 1
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((work/'app'/'initial-login.txt').read_text().strip())
            page.get_by_role('button', name='Log ind', exact=True).click()
            expect(page.locator('#ratio-dialog')).to_be_visible(timeout=20000)
            expect(page.locator('#ratio-source')).to_have_text('NordicBytes-42.torrent')
            expect(page.locator('a[download]')).to_have_attribute('href', '/static/fjordseed-chrome.zip')
            assert context.request.get(address+'static/fjordseed-chrome.zip').status == 200
            app.extensions['runtime'].rpc.assert_not_called()
            page.locator('#ratio-action').select_option('delete')
            page.locator('#ratio-limit').fill('2')
            page.locator('#ratio-save').click()
            expect(page.locator('#ratio-dialog')).not_to_be_visible()
            app.extensions['runtime'].rpc.assert_called_once()
            call = app.extensions['runtime'].rpc.call_args
            assert call.args[0] == 'add'
            assert call.args[1]['ratio_action'] == 'delete'
            assert float(call.args[1]['ratio_limit']) == 2
            assert 'torrent' in call.args[1]
            assert worker.evaluate("async () => !(await chrome.storage.session.get('pending')).pending")
            # A subsequent import reuses the same document instead of opening/reloading a tab.
            page.evaluate("window.reuseMarker = 'preserved'; location.hash = '#trackers'")
            before = len(context.pages)
            worker.evaluate("() => self.fixtureBegin('https://nordicbytes.org/torrents/download/42')")
            expect(page.locator('#ratio-dialog')).to_be_visible()
            assert len(context.pages) == before
            assert page.evaluate('window.reuseMarker') == 'preserved'
            assert worker.evaluate("async () => (await chrome.tabs.query({active:true})).some(t => t.url.includes('#trackers'))")
            app.extensions['runtime'].rpc.assert_called_once()
            page.locator('#ratio-dialog .close').click()
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            popup = context.new_page()
            popup.set_viewport_size({'width': 370, 'height': 600})
            popup.goto(worker.url.replace('background.js', 'popup.html'))
            expect(popup.locator('#address')).to_have_value(address)
            expect(popup.locator('#status')).to_contain_text('Klar i FjordSeed')
            assert popup.evaluate('document.documentElement.scrollWidth <= innerWidth')
            (root/'test-results').mkdir(exist_ok=True)
            popup.screenshot(path=str(root/'test-results'/'chrome-extension.png'))
            context.close()
    finally:
        server.shutdown()
print('Extension handoff, login, duplicate guard and manual confirmation passed; no real download.')
