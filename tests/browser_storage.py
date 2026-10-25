"""Folder chooser, errors and save flow on desktop and mobile."""
import json
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from storage import Storage
from test_app import FakeRuntime


def helper(self,action,value='',source='/'):
    if action=='temporary_usage':return {'temporary_bytes':600*1024**3,'rss_temporary_bytes':512*1024**3,'current_rss_bytes':512*1024**3}
    if action=='usage':return {'total_bytes':4*1024**4,'used_bytes':3*1024**4,'free_bytes':1024**4}
    if action=='mount':return {'ready':True}
    if action=='writable':return {'writable':True}
    return {'path':value,'parent':None if not value else '', 'free_bytes':1024**4,
            'directories':[] if value else [{'name':'Film og serier','path':'/mnt/fjordhub/Storage-pool1/fjordflix-media'}]}


with tempfile.TemporaryDirectory() as folder, patch.object(Storage,'helper',helper):
    app=create_app(folder,testing=True,runtime_factory=FakeRuntime)
    app.extensions['runtime'].host_downloads=Path('/downloads')
    app.extensions['runtime'].stop=Mock()
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            base=f'http://127.0.0.1:{server.server_port}'
            page.goto(base)
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button',name='Log ind').click()
            page.goto(base+'/#storage')
            expect(page.locator('#storage-browse')).to_be_disabled()
            expect(page.locator('#storage-proxmox')).to_be_disabled()
            expect(page.locator('[data-storage-mode-note]').first).to_contain_text('Bruger FjordFlix-lager')
            for view in ('storage','streaming'):
                page.goto(base+'/#'+view)
                card=page.locator('#'+view+'-view [data-storage-usage]')
                expect(card.locator('[data-usage-percent]')).to_have_text('75 % brugt')
                expect(card.locator('[data-usage-used]')).to_have_text('3.072,00 GiB')
                expect(card.locator('[data-usage-free]')).to_have_text('1.024,00 GiB')
                expect(card.locator('[data-usage-bar]')).to_have_attribute('value','75')
                expect(card.locator('[data-usage-temporary-label]')).to_contain_text('512,00 GiB')
                expect(card.locator('[data-usage-temporary-segment]')).to_have_css('width',__import__('re').compile(r'[1-9][0-9.]*px'))
            page.goto(base+'/#streaming')
            page.locator('#streaming-enabled').uncheck()
            page.locator('#streaming-buffer').check()
            page.locator('#streaming-save').click()
            expect(page.locator('#streaming-mode')).to_contain_text('FjordFlix er slået fra')
            page.goto(base+'/#storage')
            expect(page.locator('#storage-browse')).to_be_enabled()
            page.route('**/api/storage?proxmox=1',lambda route:route.fulfill(json={
                'storages':[{'id':'Storage-pool1','type':'dir','free_bytes':1024**4,
                    'paths':['/mnt/fjordhub/Storage-pool1','/mnt/fjordflix/pool-readonly']}],
                'mounts':[{'path':'/mnt/fjordflix/pool-readonly','read_only':True}]}))
            for width in (1440,390):
                page.set_viewport_size({'width':width,'height':900})
                expect(page.locator('#page-title')).to_have_text('Lager og mapper')
                expect(page.locator('#downloads-view')).not_to_be_visible()
                page.locator('#storage-proxmox').click()
                expect(page.locator('#storage-pool-list')).to_contain_text('Storage-pool1')
                page.locator('#storage-browse').click()
                page.get_by_role('button',name='▸ Film og serier').click()
                expect(page.locator('#storage-select')).to_be_enabled()
                assert page.locator('#storage-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
                screenshots=Path(__file__).resolve().parents[1]/'test-results';screenshots.mkdir(exist_ok=True)
                page.screenshot(path=str(screenshots/f'storage-picker-{width}.png'))
                page.locator('#storage-select').click()
                expect(page.locator('#storage-dialog')).not_to_be_visible()
                expect(page.locator('#storage-buffer')).to_contain_text('fjordflix-media/.incomplete')
                expect(page.locator('#toast')).not_to_be_visible()
                page.screenshot(path=str(screenshots/f'storage-{width}.png'))
                page.goto(base+'/#streaming')
                expect(page.locator('#streaming-view [data-usage-percent]')).to_have_text('75 % brugt')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(screenshots/f'streaming-storage-{width}.png'))
                page.locator('#streaming-view [data-storage-usage]').screenshot(path=str(screenshots/f'streaming-capacity-{width}.png'))
                page.goto(base+'/#storage')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.reload()
            page.unroute('**/api/storage?proxmox=1')
            page.route('**/api/storage?proxmox=1',lambda route:route.fulfill(status=503,json={
                'error':'FjordHub afviste lageroversigten. Opdatér FjordHub til nyeste version.',
                'error_code':'storage_integration_unavailable'}))
            page.locator('#storage-proxmox').click()
            expect(page.locator('#storage-error')).to_contain_text('Opdatér FjordHub')
            expect(page.locator('#page-title')).to_have_text('Lager og mapper')
            assert '/login' not in page.url
            assert app.extensions['state'].get()['storage']['locations'][0]['path'].endswith('fjordflix-media')
            page.route('**/api/storage/usage',lambda route:route.fulfill(status=503,json={'error':'offline'}))
            page.goto(base+'/#streaming')
            expect(page.locator('#streaming-view [data-usage-status]')).to_contain_text('Viser senest hentede tal')
            expect(page.locator('#streaming-view [data-usage-details]')).to_be_visible()
            page.unroute('**/api/storage/usage')
            page.route('**/api/storage/usage',lambda route:route.fulfill(json={
                'path':'/mnt/media','total_bytes':1000,'used_bytes':950,'free_bytes':50}))
            page.goto(base+'/#storage')
            expect(page.locator('#storage-view [data-storage-usage]')).to_have_attribute('data-level','critical')
            expect(page.locator('#storage-view [data-usage-percent]')).to_have_text('95 % brugt')
            assert not errors,errors
            browser.close()
    finally:
        server.shutdown()
print('PASS folder selection, Proxmox inventory, persisted destination, desktop/mobile and no browser errors')
