"""RSS switches against an isolated app; no Docker or real downloads."""
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime
import green_credit as credit


root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as folder:
    credit.CONFIG=Path(folder)/'qbit'
    credit.POLICIES=Path(folder)/'green-policy.json'
    app=create_app(folder,testing=True,runtime_factory=FakeRuntime)
    store=app.extensions['rss']
    ident=store.save(dict(name='Politijagt',url='https://tracker.example/rss?passkey=private',
                         folder='',enabled=True,ratio_limit=2,ratio_action='keep'))
    store.save(dict(name='Temptation Island Danmark med et meget langt feednavn',
                    url='https://tracker.example/other',folder='',enabled=False,ratio_limit=3,ratio_action='delete_ratio'))
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/#rss')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button',name='Log ind').click()
            page.locator('.nav[href="#rss"]').click()
            switch=page.get_by_role('switch',name='Automatisk hentning for Politijagt',exact=True)
            expect(switch).to_have_attribute('aria-checked','true')
            card=page.locator('.rss-feed-card').first
            expect(card.locator('.rss-feed-upload-value')).to_have_text('Afventer uploadtal')
            with credit.CreditLedger().transaction() as ledger:
                ledger.update({'hash':'a'*40,'uploaded':6*1024**3,'tags':'FjordSeed-RSS-'+ident},now=20)
                ledger.update({'hash':'b'*40,'uploaded':256*1024**2,'tags':'FjordSeed-RSS-'+ident},now=20)
                ledger.entries.pop('a'*40)
            page.evaluate('refreshRss()')
            expect(card.locator('.rss-feed-upload-value')).to_have_text('6.3 GB')
            expect(page.locator('.rss-feed-card').nth(1).locator('.rss-feed-upload-value')).to_have_text('0.0 B')
            switch.click()
            expect(switch).to_be_enabled()
            expect(switch).to_have_attribute('aria-checked','false')
            assert store.entries()[0]['enabled'] is False
            page.reload()
            expect(switch).to_have_attribute('aria-checked','false')
            expect(card.locator('.rss-feed-upload-value')).to_have_text('6.3 GB')
            switch.focus()
            page.keyboard.press('Space')
            expect(switch).to_have_attribute('aria-checked','true')
            expect(switch).to_be_focused()
            assert store.entries()[0]['enabled'] is True
            card.get_by_role('button',name='Vis detaljer for Politijagt',exact=True).last.click()
            expect(card.locator('.rss-feed-details')).to_be_visible()
            endpoint='**/api/rss/'+ident+'/enabled'
            page.route(endpoint,lambda route:route.fulfill(status=400,content_type='application/json',body='{"error":"Test: could not save"}'))
            switch.click()
            expect(page.locator('#toast')).to_contain_text('Test: could not save')
            expect(switch).to_be_enabled()
            expect(switch).to_have_attribute('aria-checked','true')
            assert store.entries()[0]['enabled'] is True
            expect(card.locator('.rss-feed-details')).to_be_visible()
            page.unroute(endpoint)
            # A pending save disables repeat clicks and competing edit actions.
            pending=[]
            page.route(endpoint,lambda route:pending.append(route))
            switch.click()
            expect(switch).to_be_disabled()
            expect(card.get_by_role('button',name='Rediger',exact=True)).to_be_disabled()
            expect(switch).to_contain_text('Gemmer')
            assert len(pending)==1
            pending[0].continue_()
            expect(switch).to_be_enabled()
            expect(switch).to_have_attribute('aria-checked','false')
            page.unroute(endpoint)
            output=root/'test-results'
            output.mkdir(exist_ok=True)
            page.screenshot(path=str(output/'rss-upload-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            expect(switch).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            switch.click()
            expect(switch).to_have_attribute('aria-checked','true')
            page.screenshot(path=str(output/'rss-upload-mobile.png'),full_page=True)
            assert not errors,errors
            browser.close()
    finally:
        server.shutdown()
print('PASS: RSS credit totals, switch persistence, keyboard focus, error recovery, pending save, desktop/mobile.')
