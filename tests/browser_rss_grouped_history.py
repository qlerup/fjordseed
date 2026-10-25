"""Grouped archive, exclusion and legacy-feed import without real downloads."""
from pathlib import Path
import sys,tempfile,threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime
import green_credit as credit

with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);credit.CONFIG=root/'qbit';credit.POLICIES=root/'policy.json'
    app=create_app(folder,testing=True,runtime_factory=FakeRuntime)
    store=app.extensions['rss']
    old=store.save(dict(name='Gammelt seriefeed',url='https://tracker.example/old',enabled=False,ratio_limit=2))
    ident=store.save(dict(name='Dansk TV',url='https://tracker.example/all',enabled=False,ratio_limit=2))
    with credit.CreditLedger().transaction() as ledger:
        for i in range(45):
            title='Politijagt.S01E'+str(i).zfill(2)+'.DANiSH.1080p.WEB-DL'
            ledger.update(dict(hash=f'{i:040x}',name=title,tags='FjordSeed-RSS-'+old,uploaded=765*1024**2,downloaded=2*1024**3,added_on=10),now=20+i)
        ledger.record_rss_title(old,'f'*40,'Serie æøå <img src=x onerror=alert(1)>.S01E01.1080p')
    store.save({**next(f for f in store.entries() if f['id']==ident),'history_sources':[old]})
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}/#rss')
            page.locator('[name=username]').fill('admin');page.locator('[name=password]').fill((root/'initial-login.txt').read_text().strip())
            page.get_by_role('button',name='Log ind').click();page.locator('.nav[href="#rss"]').click()
            expect(page.locator('#page-title')).to_have_text('Dine RSS-feeds')
            page.locator('#rss-manage').click()
            expect(page.locator('.rss-feed-card')).to_have_count(2)
            for width in (1440,390):
                page.set_viewport_size({'width':width,'height':844})
                page.get_by_role('button',name='Downloadhistorik for Dansk TV',exact=True).click()
                expect(page.locator('#rss-history-status')).to_have_text('46 torrents · 2 grupper')
                expect(page.locator('.rss-history-group')).to_have_count(2)
                group=page.locator('.rss-history-group').filter(has=page.locator('strong',has_text='Politijagt'))
                expect(group.locator('.rss-history-group-stats')).to_contain_text('34 GB')
                expect(group.locator('.rss-history-group-stats')).to_contain_text('765 MB')
                expect(group.locator('.rss-history-group-stats')).to_contain_text('90 GB')
                out=Path(__file__).resolve().parents[1]/'test-results';out.mkdir(exist_ok=True)
                page.screenshot(path=str(out/f'rss-history-overview-{width}.png'))
                group.locator('summary').first.click()
                expect(group.locator('.rss-history-file')).to_have_count(40)
                group.get_by_role('button',name='Vis flere filer').click()
                expect(group.locator('.rss-history-file')).to_have_count(45)
                group.locator('.rss-history-file summary').first.click()
                expect(group.locator('.rss-history-metrics').first).to_contain_text('765 MB')
                expect(group.locator('.rss-history-metrics').first).to_contain_text('2.0 GB')
                expect(group.locator('.rss-history-metrics').first).to_contain_text('Ukendt')
                expect(page.locator('#rss-history-list img')).to_have_count(0)
                dialog=page.locator('#rss-history-dialog')
                assert dialog.evaluate('e=>e.scrollWidth<=e.clientWidth+1')
                out=Path(__file__).resolve().parents[1]/'test-results';out.mkdir(exist_ok=True)
                page.screenshot(path=str(out/f'rss-grouped-history-{width}.png'))
                group.get_by_role('button',name='Udeluk',exact=True).click()
                confirmation=page.locator('#rss-exclude-dialog')
                expect(confirmation).to_be_visible()
                expect(confirmation).to_contain_text('Politijagt')
                expect(confirmation).to_contain_text('Rediger feed → Titelfilter → Undgå')
                expect(confirmation.get_by_role('button',name='Annuller',exact=True)).to_be_focused()
                assert next(f for f in store.entries() if f['id']==ident)['title_exclude']==[]
                assert confirmation.evaluate('e=>e.scrollWidth<=e.clientWidth+1')
                page.screenshot(path=str(out/f'rss-exclude-confirm-{width}.png'))
                confirmation.get_by_role('button',name='Annuller',exact=True).click()
                expect(confirmation).not_to_be_visible()
                expect(group.get_by_role('button',name='Udeluk',exact=True)).to_be_focused()
                if width==390:
                    group.get_by_role('button',name='Udeluk',exact=True).click()
                    page.keyboard.press('Escape')
                    expect(confirmation).not_to_be_visible()
                    assert next(f for f in store.entries() if f['id']==ident)['title_exclude']==[]
                    group.get_by_role('button',name='Udeluk',exact=True).click()
                    page.route('**/api/rss/*/history/exclude',lambda route:route.fulfill(status=503,json={'error':'Prøv igen senere'}))
                    confirmation.get_by_role('button',name='Ja, udeluk titlen',exact=True).click()
                    expect(confirmation.locator('#rss-exclude-error')).to_have_text('Prøv igen senere')
                    page.unroute('**/api/rss/*/history/exclude')
                    confirmation.get_by_role('button',name='Ja, udeluk titlen',exact=True).click()
                    expect(confirmation).not_to_be_visible()
                    expect(group.get_by_role('button',name='Udelukket')).to_be_disabled()
                    assert next(f for f in store.entries() if f['id']==ident)['title_exclude']==['Politijagt']
                    page.locator('#rss-history-search').fill('Politijagt')
                    expect(group.get_by_role('button',name='Udelukket')).to_be_disabled()
                dialog.get_by_role('button',name='Luk',exact=True).click()
            # Mixed known/missing credit must not turn unknown measurements into zero.
            fixture={'count':3,'groups':[{'key':'mixed','title':'Blandet historik','exclude_title':'Blandet historik','excluded':False,'downloads':[
                {'title':'Episode 1','credited_uploaded':1024**3,'downloaded':2*1024**3},
                {'title':'Episode 2','credited_uploaded':3*1024**3,'downloaded':4*1024**3},
                {'title':'Episode 3','upload_credit_pending':True,'credited_uploaded':0}]}]}
            import json
            page.route('**/api/rss/*/history/groups',lambda route:route.fulfill(content_type='application/json',body=json.dumps(fixture)))
            page.get_by_role('button',name='Downloadhistorik for Dansk TV',exact=True).click()
            numbers=page.locator('.rss-history-group-stats')
            expect(numbers).to_contain_text('4.0 GB')
            expect(numbers).to_contain_text('2.0 GB')
            expect(numbers).to_contain_text('6.0 GB')
            expect(numbers).to_contain_text('Foreløbigt')
            page.locator('.rss-history-group summary').first.click()
            expect(page.locator('.rss-history-file summary').last).to_contain_text('Ukendt')
            page.locator('#rss-history-search').fill('findes ikke')
            expect(page.locator('.rss-history-group')).to_have_count(0)
            expect(page.locator('.rss-history-empty')).to_be_visible()
            page.locator('#rss-history-search').fill('BLANDET')
            expect(page.locator('.rss-history-group')).to_have_count(1)
            page.locator('#rss-history-dialog').get_by_role('button',name='Luk',exact=True).click()
            page.unroute('**/api/rss/*/history/groups')
            page.route('**/api/rss/*/history/groups',lambda route:route.fulfill(status=503,content_type='application/json',body='{"error":"Historik afventer"}'))
            page.get_by_role('button',name='Downloadhistorik for Dansk TV',exact=True).click()
            expect(page.locator('#rss-history-status')).to_have_text('Historik afventer')
            assert not errors,errors
            browser.close()
    finally:server.shutdown()
print('PASS grouped RSS history, archive import, metrics, exclusion, paging, safe text, desktop/mobile and errors')
