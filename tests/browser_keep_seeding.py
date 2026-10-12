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
    if action=='mount':return {'ready':True}
    if action=='writable':return {'writable':True}
    return {'path':value,'parent':None if not value else '', 'free_bytes':1024**4,
            'directories':[] if value else [{'name':'Film og serier','path':'/mnt/fjordhub/Storage-pool1/fjordflix-media'}]}


with tempfile.TemporaryDirectory() as folder, patch.object(Storage,'helper',helper):
    app=create_app(folder,testing=True,runtime_factory=FakeRuntime)
    app.extensions['state'].save('a'*32,True)
    app.extensions['runtime'].host_downloads=Path('/downloads')
    app.extensions['runtime'].stop=Mock()
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch();page=browser.new_page(bypass_csp=True);errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            base=f'http://127.0.0.1:{server.server_port}'
            page.goto(base)
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button',name='Log ind').click()

            page.wait_for_function("typeof updateSeedingFields==='function' && typeof rssShowStep==='function'")
            for prefix,dialog,field in [('ratio','ratio-dialog','ratio-limit'),('rss','rss-dialog','rss-ratio')]:
                page.evaluate("""({prefix,dialog})=>{
                    document.querySelector('#'+dialog).showModal();
                    if(prefix==='rss')rssShowStep(true);
                    updateSeedingFields(prefix);
                }""",{'prefix':prefix,'dialog':dialog})
                expect(page.locator('#'+field)).not_to_be_visible()
                page.locator('#'+prefix+'-action').select_option('delete')
                expect(page.locator('#'+field)).to_be_visible()
                assert page.locator('#'+prefix+'-action').bounding_box()['y'] < page.locator('#'+field).bounding_box()['y']
                page.locator('#'+field).fill('')
                page.locator('#'+prefix+'-action').select_option('keep')
                expect(page.locator('#'+field)).not_to_be_visible()
                expect(page.locator('#'+field)).to_be_disabled()
                page.locator('#'+prefix+'-action').select_option('delete_ratio')
                expect(page.locator('#'+field)).to_be_visible()
                expect(page.locator('#'+prefix+'-delete-notice')).to_contain_text('uden tidsgrænse')
                page.evaluate('(id)=>document.getElementById(id).close()',dialog)
            page.evaluate("openRatioEditor({name:'Test',share_limit_action:'Stop',ratio_limit:1,ratio:50,seeding_time:300000})")
            expect(page.locator('#edit-ratio-limit')).not_to_be_visible()
            expect(page.locator('#edit-ratio-warning')).not_to_be_visible()
            page.locator('#edit-ratio-action').select_option('delete')
            expect(page.locator('#edit-ratio-limit')).to_be_visible()
            expect(page.locator('#edit-ratio-warning')).to_be_visible()
            page.locator('#edit-extra-seed-hours').fill('1')
            expect(page.locator('#edit-extra-seed-info')).to_contain_text('50 timer')
            page.locator('#edit-ratio-action').select_option('keep')
            expect(page.locator('#edit-extra-seed-hours')).not_to_be_visible()
            expect(page.locator('#edit-ratio-warning')).not_to_be_visible()
            page.locator('#edit-ratio-action').select_option('delete_ratio')
            expect(page.locator('#edit-ratio-limit')).to_be_visible()
            expect(page.locator('#edit-extra-seed-hours')).not_to_be_visible()
            expect(page.locator('#edit-ratio-info')).to_contain_text('uden tidsgrænse')
            page.evaluate("""()=>{document.querySelectorAll('dialog[open]').forEach(d=>d.close());
                document.body.append(torrentProgress({name:'Moving',state:'moving',move_progress:.42}));}""")
            expect(page.locator('.move-progress')).to_have_attribute('value','0.42')
            expect(page.locator('.is-moving')).to_contain_text('42 %')
            expect(page.locator('.is-moving .seed-state')).to_contain_text('Flytter filer')
            assert 'Seeder' not in page.locator('.is-moving').inner_text()
            assert 'Seeding:' not in page.locator('.is-moving').inner_text()
            page.evaluate("""()=>{current={ready:true};const host=document.createElement('div');
                host.id='toggle-test';document.querySelector('#torrent-list').append(host);}""")
            for state,label in [('downloading','Pause'),('stalledUP','Pause'),('queuedDL','Pause'),
                                ('pausedUP','Start'),('pausedDL','Start'),('stoppedUP','Start'),('stoppedDL','Start'),
                                ('moving','Pause')]:
                page.evaluate("""state=>document.querySelector('#toggle-test').replaceChildren(card({
                    hash:'a'.repeat(40),name:'Toggle fixture',state,progress:1,seeding_requirement_met:true}))""",state)
                host=page.locator('#toggle-test')
                assert host.get_by_role('button',name='Start Toggle fixture',exact=True).count()+host.get_by_role('button',name='Pause Toggle fixture',exact=True).count()==1
                button=host.get_by_role('button',name=label+' Toggle fixture',exact=True)
                expect(button).to_be_disabled() if state=='moving' else expect(button).to_be_enabled()
            page.evaluate("""()=>document.querySelector('#toggle-test').replaceChildren(card({
                hash:'a'.repeat(40),name:'Toggle fixture',state:'stoppedUP',progress:1,seeding_requirement_met:true}))""")
            page.get_by_role('button',name='Start Toggle fixture',exact=True).click()
            expect(page.locator('#toggle-test')).to_have_count(0)
            assert app.extensions['runtime'].rpc.call_args.args[0]=='start'
            page.evaluate("""()=>{current={ready:true};document.querySelector('#torrent-list').append(card({
                hash:'a'.repeat(40),name:'Toggle fixture',state:'stalledUP',progress:1,seeding_requirement_met:false}));}""")
            page.get_by_role('button',name='Pause Toggle fixture',exact=True).click()
            expect(page.locator('#stop-dialog')).to_be_visible()
            assert app.extensions['runtime'].rpc.call_count==1
            page.locator('#stop-save').click()
            expect(page.locator('#stop-dialog')).not_to_be_visible()
            assert app.extensions['runtime'].rpc.call_args.args[0]=='stop'
            assert app.extensions['runtime'].rpc.call_args.args[1]['confirm_early_stop'] is True
            page.evaluate("""()=>{const bar=torrentProgress({state:'stalledUP',progress:1,
                ratio_only:true,credited_ratio:.5,ratio:1,ratio_limit:2,
                seeding_time:3600*1000,seeding_time_limit:2940});bar.id='ratio-only-test';
                document.body.append(bar);}""")
            assert page.locator('#ratio-only-test .seed-progress').evaluate('e=>e.value')==.25
            assert '25 %' in page.locator('#ratio-only-test').inner_text()
            assert not errors,errors
            browser.close()
            print('PASS manual, RSS and existing-torrent keep/delete fields and warnings')
    finally:
        server.shutdown()
