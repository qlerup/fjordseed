"""Unified download navigation and all three sources, against an isolated app."""
from pathlib import Path
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

class Demo(FakeRuntime):
    def status(self):
        torrents=[dict(hash='a'*40,name='Min manuelle torrent',state='downloading',progress=.4,size=1024**3,dlspeed=1024**2,upspeed=0,ratio=0),
                  dict(hash='b'*40,name='En automatisk serie med et langt navn fra mit feed',state='uploading',progress=1,size=1024**3,dlspeed=0,upspeed=2*1024**2,ratio=1,tags='FjordSeed-RSS-test')]
        torrents.extend([dict(hash='c'*40,name='Manuel inaktiv',state='stoppedUP',progress=1,dlspeed=0,upspeed=0),
                         dict(hash='d'*40,name='RSS inaktiv',state='stoppedUP',progress=1,dlspeed=0,upspeed=0,tags='FjordSeed-RSS-test')])
        return {**super().status(),'ready':True,'enabled':True,'torrents':torrents}

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as folder:
    app=create_app(folder,testing=True,runtime_factory=Demo)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button',name='Log ind',exact=True).click()
            page.locator('.nav[href="#torrents"]').click()
            expect(page.locator('#page-title')).to_have_text('Dine downloads')
            expect(page.locator('#count')).to_have_text('4')
            expect(page.locator('#torrent-list')).to_contain_text('Min manuelle torrent')
            expect(page.locator('#torrent-list')).to_contain_text('En automatisk serie')
            expect(page.locator('#rss-view')).to_be_hidden()
            expect(page.locator('#manual-active-heading')).to_have_text('Aktive torrents (2)')
            expect(page.locator('#manual-inactive-summary')).to_have_text('Inaktive torrents (2)')
            page.locator('#manual-inactive-summary').click()
            expect(page.locator('#manual-inactive-list')).to_contain_text('Manuel inaktiv')
            expect(page.locator('#manual-inactive-list')).to_contain_text('RSS inaktiv')
            page.locator('[data-download-filter=manual]').click()
            expect(page.locator('#rss-view')).to_be_hidden()
            expect(page.locator('#count')).to_have_text('2')
            expect(page.locator('#torrent-list')).not_to_contain_text('En automatisk serie')
            expect(page.locator('#manual-inactive-summary')).to_have_text('Inaktive torrents (1)')
            page.locator('[data-download-filter=rss]').click()
            expect(page.locator('#downloads-view')).to_be_hidden()
            expect(page.locator('#rss-torrent-list')).to_contain_text('En automatisk serie')
            expect(page.locator('#rss-inactive-summary')).to_have_text('Inaktive torrents (1)')
            expect(page.locator('#ul')).to_have_text('2.0 MB/s')
            page.locator('[data-download-filter=all]').click()
            page.screenshot(path=str(root/'test-results/downloads-desktop.png'),full_page=True)
            page.locator('#new-torrent').click()
            expect(page.locator('#torrent-file')).to_be_visible()
            page.locator('#method-magnet').click()
            page.locator('#magnet').fill('invalid')
            page.locator('#add-save').click()
            expect(page.locator('#add-error')).to_be_visible()
            page.locator('#magnet').fill('magnet:?xt=urn:btih:'+'a'*40)
            page.locator('#method-rss').click()
            page.locator('#rss-name').fill('Mit feed')
            page.locator('#rss-url').fill('https://example.test/rss')
            page.locator('#method-magnet').click()
            expect(page.locator('#magnet')).to_have_value('magnet:?xt=urn:btih:'+'a'*40)
            page.locator('#add-save').click()
            expect(page.locator('#ratio-dialog')).to_be_visible()
            page.locator('#ratio-back').click()
            page.locator('#method-rss').click()
            expect(page.locator('#rss-name')).to_have_value('Mit feed')
            page.locator('#rss-next').click()
            expect(page.locator('#rss-seeding-step')).to_be_visible()
            page.locator('#rss-back').click()
            page.locator('#rss-next').click()
            page.locator('#rss-save').click()
            expect(page.locator('#add-dialog')).to_be_hidden()
            assert app.extensions['rss'].entries()[0]['name']=='Mit feed'
            page.locator('#downloads-manage-feeds').click()
            page.get_by_role('button',name='Rediger',exact=True).click()
            expect(page.locator('#add-title')).to_have_text('Rediger RSS-feed')
            expect(page.locator('.unified-add .add-method')).to_be_hidden()
            page.locator('#rss-cancel').click()
            page.locator('#rss-feeds-dialog .dialog-footer .close').click()
            for width in (390,320):
                page.set_viewport_size({'width':width,'height':900})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                page.screenshot(path=str(root/f'test-results/downloads-{width}.png'),full_page=True)
                page.locator('#new-torrent').click()
                page.locator('#method-rss').click()
                assert page.locator('#add-dialog').evaluate('el=>el.scrollWidth<=el.clientWidth')
                page.screenshot(path=str(root/f'test-results/add-source-{width}.png'))
                page.keyboard.press('Escape')
            assert not errors,errors
            browser.close()
    finally: server.shutdown()
print('PASS unified filters, totals, magnet validation, source switching, RSS create/edit, mobile and console')
