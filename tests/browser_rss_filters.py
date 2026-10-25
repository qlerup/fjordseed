"""Title filter editor with isolated data; no Docker or downloads."""
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime


root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as folder:
    app=create_app(folder,testing=True,runtime_factory=FakeRuntime)
    store=app.extensions['rss']
    store.save(dict(name='Dansk TV',url='https://tracker.example/rss?key=private',folder='',
                    enabled=True,ratio_limit=2,ratio_action='keep',title_exclude=['Politijagt']))
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button',name='Log ind').click()
            page.locator('.nav[href="#torrents"]').click();page.locator('[data-download-filter=rss]').click();page.locator('#downloads-manage-feeds').click()
            page.locator('.rss-feed-card').first.get_by_role('button',name='Rediger',exact=True).click()
            page.locator('#rss-open-filters').click()
            dialog=page.locator('#rss-filter-dialog')
            include=page.locator('#rss-filter-include-list')
            exclude=page.locator('#rss-filter-exclude-list')
            expect(exclude).to_contain_text('Politijagt')
            page.locator('#rss-filter-include-input').fill('Badehotellet')
            page.locator('#rss-filter-include-input').press('Enter')
            expect(include).to_contain_text('Badehotellet')
            expect(dialog).to_be_visible()
            include.locator('.rss-filter-item').drag_to(exclude)
            expect(exclude).to_contain_text('Badehotellet')
            expect(include).not_to_contain_text('Badehotellet')
            page.locator('#rss-filter-include-input').fill('POLITIJAGT')
            page.locator('#rss-filter-include-add').click()
            expect(page.locator('#rss-filter-error')).to_contain_text('findes allerede')
            exclude.locator('input[value="Politijagt"]').check()
            page.locator('#rss-filter-exclude-move').click()
            expect(include).to_contain_text('Politijagt')
            include.locator('input[value="Politijagt"]').check()
            page.locator('#rss-filter-include-remove').click()
            expect(include).not_to_contain_text('Politijagt')
            # Escape discards the editor draft and returns to the RSS form.
            page.keyboard.press('Escape')
            expect(dialog).not_to_be_visible()
            expect(page.locator('#add-dialog')).to_be_visible()
            expect(page.locator('#rss-open-filters')).to_be_focused()
            page.locator('#rss-open-filters').click()
            expect(exclude).to_contain_text('Politijagt')
            expect(exclude).not_to_contain_text('Badehotellet')
            page.locator('#rss-filter-include-input').fill('Den store bagedyst')
            page.locator('#rss-filter-include-add').click()
            # Rendering title text must never create injected HTML.
            page.locator('#rss-filter-exclude-input').fill('<img src=x onerror=alert(1)>')
            page.locator('#rss-filter-exclude-add').click()
            assert exclude.locator('img').count()==0
            output=root/'test-results';output.mkdir(exist_ok=True)
            page.screenshot(path=str(output/'rss-filters-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert dialog.evaluate('el=>el.scrollWidth<=el.clientWidth')
            page.screenshot(path=str(output/'rss-filters-mobile.png'),full_page=True)
            page.locator('#rss-filter-apply').click()
            expect(page.locator('#rss-filter-summary')).to_have_text('1 i Kig efter · 2 i Undgå')
            assert store.entries()[0]['title_include']==[]
            page.locator('#rss-next').click()
            page.locator('#rss-save').click()
            expect(page.locator('#add-dialog')).not_to_be_visible()
            assert store.entries()[0]['title_include']==['Den store bagedyst']
            assert store.entries()[0]['title_exclude']==['Politijagt','<img src=x onerror=alert(1)>']
            page.reload()
            page.locator('#downloads-manage-feeds').click()
            page.locator('.rss-feed-card').first.get_by_role('button',name='Rediger',exact=True).click()
            page.locator('#rss-open-filters').click()
            expect(include).to_contain_text('Den store bagedyst')
            expect(exclude).to_contain_text('Politijagt')
            dialog.get_by_role('button',name='Annuller',exact=True).click()
            page.locator('#rss-cancel').click()
            page.locator('#rss-feeds-dialog .dialog-footer .close').click()
            # A new feed starts with empty lists, independently of the edited feed.
            page.locator('#new-torrent').click();page.locator('#method-rss').click()
            page.locator('#rss-name').fill('Dansk TV uden Politijagt')
            page.locator('#rss-url').fill('https://tracker.example/other')
            page.locator('#rss-start').select_option('all')
            page.locator('#rss-enabled').check()
            page.locator('#rss-open-filters').click()
            expect(include).to_contain_text('Alle titler tillades')
            expect(exclude).to_contain_text('Ingen titler udelukkes')
            page.locator('#rss-filter-exclude-input').fill('Politijagt')
            page.locator('#rss-filter-exclude-add').click()
            page.locator('#rss-filter-apply').click()
            page.locator('#rss-next').click()
            page.locator('#rss-save').click()
            expect(page.locator('#add-dialog')).not_to_be_visible()
            assert store.entries()[1]['title_include']==[]
            assert store.entries()[1]['title_exclude']==['Politijagt']
            assert not errors,errors
            browser.close()
    finally:
        server.shutdown()
print('PASS: title editor add/remove, drag/drop, keyboard move, cancel, persistence, new feed, mobile and safe rendering.')
