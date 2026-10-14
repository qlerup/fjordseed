"""Persistent RSS titles/upload modal on desktop and mobile without real downloads."""
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime
import green_credit as credit


with tempfile.TemporaryDirectory() as folder:
    credit.CONFIG = Path(folder)/'qbit'
    credit.POLICIES = Path(folder)/'green-policy.json'
    app = create_app(folder, testing=True, runtime_factory=FakeRuntime)
    ident = app.extensions['rss'].save(dict(name='Politijagt', url='https://tracker.example/rss',
        enabled=False, ratio_limit=2, ratio_action='keep'))
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width':1440, 'height':1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/#rss')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button', name='Log ind').click()
            page.locator('.nav[href="#rss"]').click()
            card = page.locator('.rss-feed-card').first
            button = card.get_by_role('button', name='Hentede titler', exact=True)
            expect(button).not_to_be_visible()
            card.get_by_role('button', name='Vis detaljer for Politijagt', exact=True).last.click()
            button.click()
            expect(page.locator('#rss-history-status')).to_have_text('Ingen hentede titler registreret endnu.')
            page.keyboard.press('Escape')
            with credit.CreditLedger().transaction() as ledger:
                for i in range(30):
                    row = dict(hash=f'{i:040x}', name=('Film æøå <img src=x onerror=alert(1)> ' if i == 0 else 'Politijagt S01E')+str(i)+' langtitel'*10,
                        uploaded=765*1024**2, tags='FjordSeed-RSS-'+ident)
                    ledger.update(row, now=20+i)
                    ledger.entries.pop(row['hash'])
            for width in (1440, 390):
                page.set_viewport_size({'width':width, 'height':844})
                button.click()
                expect(page.locator('#rss-history-list li')).to_have_count(30)
                expect(page.locator('#rss-history-list')).to_contain_text('Film æøå <img src=x onerror=alert(1)>')
                expect(page.locator('#rss-history-list img')).to_have_count(0)
                expect(page.locator('.rss-history-credit strong').first).to_have_text('765 MB')
                dialog = page.locator('#rss-history-dialog')
                assert dialog.evaluate('e=>e.scrollWidth<=e.clientWidth+1')
                output = Path(__file__).resolve().parents[1]/'test-results'
                output.mkdir(exist_ok=True)
                page.screenshot(path=str(output/f'rss-history-{width}.png'))
                dialog.get_by_role('button', name='Luk', exact=True).click()
                expect(dialog).not_to_be_visible()
                expect(button).to_be_focused()
            page.reload()
            card.get_by_role('button', name='Vis detaljer for Politijagt', exact=True).last.click()
            page.route('**/api/rss/*/history', lambda route: route.fulfill(status=503,
                content_type='application/json', body='{"error":"Historik afventer"}'))
            button.click()
            expect(page.locator('#rss-history-status')).to_have_text('Historik afventer')
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
print('PASS RSS title history, retained credit, empty/error states, safe text, desktop/mobile modal and focus')
