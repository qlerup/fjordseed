"""Exercise running torrent ratio edits with an isolated fake client."""
import sys, tempfile, threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

row = {'hash':'a'*40,'name':'Running Linux release','state':'stalledUP','progress':1,
       'size':1073741824,'ratio':1,'ratio_limit':2,'seeding_time':7200,
       'seeding_time_limit':2880,'share_limit_action':'RemoveWithContent'}
class Demo(FakeRuntime):
    def status(self):
        return {**super().status(), 'ready':True, 'torrents':[dict(row)]}

with tempfile.TemporaryDirectory() as folder:
    app=create_app(folder,testing=True,runtime_factory=Demo)
    app.extensions['state'].save('b'*32,True)
    def rpc(action,data):
        assert action=='ratio'
        row['ratio_limit']=data['ratio_limit']
        row['share_limit_action']='RemoveWithContent' if data['ratio_action']=='delete' else 'Stop'
        return {'ok':True}
    app.extensions['runtime'].rpc.side_effect=rpc
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button',name='Log ind').click()
            for width,target,action in [(1440,5,'keep'),(390,2.5,'delete')]:
                page.set_viewport_size({'width':width,'height':960})
                page.get_by_role('button',name='Ratio Running Linux release',exact=True).click()
                dialog=page.locator('#edit-ratio-dialog')
                expect(dialog).to_be_visible()
                page.locator('#edit-ratio-limit').fill(str(target))
                page.locator('#edit-ratio-action').select_option(action)
                page.locator('#edit-ratio-save').click()
                expect(dialog).not_to_be_visible()
                expect(page.locator('.torrent-metrics dd').nth(2)).to_contain_text(str(target).replace('.',','))
                assert row['share_limit_action']==('RemoveWithContent' if action=='delete' else 'Stop')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.get_by_role('button',name='Ratio Running Linux release',exact=True).click()
            page.locator('#edit-ratio-limit').fill('1')
            expect(page.locator('#edit-ratio-warning')).to_be_visible()
            expect(page.locator('#edit-ratio-warning')).to_contain_text('slettet automatisk')
            page.locator('#edit-ratio-action').select_option('keep')
            expect(page.locator('#edit-ratio-warning')).to_contain_text('Seeding kan stoppe automatisk')
            expect(page.locator('#edit-ratio-warning')).not_to_contain_text('slettet')
            page.locator('#edit-ratio-dialog .close').last.click()
            assert row['ratio_limit']==2.5
            assert app.extensions['runtime'].rpc.call_count==2
            row.update(credited_ratio=.5,green_until=1900000000,green_active=True,credited_uploaded=512*1024**2)
            page.reload()
            page.get_by_role('button',name='Ratio Running Linux release',exact=True).click()
            page.locator('#edit-ratio-limit').fill('1')
            expect(page.locator('#edit-ratio-warning')).not_to_be_visible()
            page.locator('#edit-ratio-dialog .close').last.click()
            assert not errors,errors
            browser.close()
            print('PASS running ratio edits, mobile/desktop, existing delete action, reached-goal warning and cancel')
    finally:server.shutdown()
