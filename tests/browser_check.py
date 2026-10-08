"""Isolated UI test: fake runtime, no Docker or downloads."""
from pathlib import Path
import json
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
        result=super().status()
        result['profiles']=[{'id':'a'*32,'name':'Seedbox VPN','desired':True,'relay_enabled':False}]
        if self.state.get()['enabled']:
            result.update(ready=True,message='VPN klar',public_ip='203.0.113.5',country='PS',port=45001,version='5.2.1',
                torrents=[{'hash':'b'*40,'name':'Test Linux ISO','progress':.42,'size':1234567890,'dlspeed':2000000,'upspeed':15000,'ratio':.1,'state':'downloading'}])
            feeds=json.loads((self.state.root/'rss.json').read_text())
            if feeds:
                result['torrents'].append({'hash':'c'*40,'name':'RSS Linux release','progress':.6,
                    'size':1000000000,'dlspeed':1000000,'upspeed':12000,'ratio':.2,'state':'downloading',
                    'tags':'FjordSeed-RSS-'+feeds[0]['id'],'eta':400})
        return result


root=Path(__file__).resolve().parents[1]
(root/'test-results').mkdir(exist_ok=True)
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
            page.get_by_role('button',name='Log ind').click()
            expect(page.locator('#new-torrent')).to_be_disabled()
            expect(page.locator('#traffic-flow')).to_have_attribute('data-state','blocked')
            expect(page.locator('#connection')).not_to_be_visible()
            page.locator('.nav[href="#connection"]').click()
            expect(page.locator('#connection')).to_be_visible()
            expect(page.locator('#downloads-view')).not_to_be_visible()
            expect(page.locator('.nav[href="#connection"]')).to_have_attribute('aria-current','page')
            page.reload()
            expect(page.locator('#connection')).to_be_visible()
            page.locator('#profile').select_option('a'*32)
            page.locator('#connect').click()
            expect(page.locator('#new-torrent')).to_be_enabled()
            expect(page.locator('#traffic-flow')).to_have_attribute('data-state','active')
            expect(page.locator('#flow-vpn-icon img')).to_have_attribute('src','/static/flags/ps.svg')
            assert page.locator('.flow-link i').first.evaluate("el=>getComputedStyle(el).animationName")=='flow-out'
            expect(page.locator('#public-address')).to_contain_text('Palæstina')
            page.locator('.nav[href="#torrents"]').click()
            expect(page.locator('#connection')).not_to_be_visible()
            expect(page.locator('#downloads-view')).to_be_visible()
            page.locator('.nav[href="#rss"]').click()
            expect(page.locator('#rss-view')).to_be_visible()
            expect(page.locator('#downloads-view')).not_to_be_visible()
            page.locator('#rss-name').fill('Linux feed')
            page.locator('#rss-url').fill('https://tracker.example/rss?passkey=fixture-secret')
            page.locator('#rss-folder').fill('linux/releases')
            page.locator('#rss-ratio').fill('3')
            page.locator('#rss-save').click()
            expect(page.locator('#rss-feed-list')).to_contain_text('Linux feed')
            expect(page.locator('#rss-feed-list')).to_contain_text('Stop-ratio: 3')
            page.evaluate('refresh()')
            expect(page.locator('#rss-torrent-list')).to_contain_text('RSS Linux release')
            expect(page.locator('#rss-torrent-list .progress')).to_have_js_property('value',.6)
            expect(page.locator('#rss-torrent-list .progress-caption')).to_contain_text('60.0 %')
            expect(page.locator('#rss-torrent-list')).not_to_contain_text('Test Linux ISO')
            page.locator('#rss-feed-list').get_by_role('button',name='Rediger').click()
            expect(page.locator('#rss-url')).to_have_value('')
            page.locator('#rss-save').click()
            expect(page.locator('#rss-feed-list')).to_contain_text('Linux feed')
            page.screenshot(path=str(root/'test-results/desktop-rss.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(root/'test-results/mobile-rss.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1000})
            page.locator('.nav[href="#torrents"]').click()
            expect(page.locator('#torrent-list')).to_contain_text('Test Linux ISO')
            expect(page.locator('#torrent-list')).not_to_contain_text('RSS Linux release')
            expect(page.locator('#torrent-list .progress')).to_have_js_property('value',.42)
            page.locator('.nav[href="#trackers"]').click()
            expect(page.locator('#trackers-view')).to_be_visible()
            expect(page.locator('#downloads-view')).not_to_be_visible()
            expect(page.locator('#traffic-flow')).not_to_be_visible()
            page.locator('#tracker-key').fill('fixture-key-not-real')
            app.extensions['trackers'].fetch=lambda entry: {'username':'Demo konto','stats':{'uploaded':10*1024**3,'downloaded':5*1024**3,'ratio':2,'buffer':5*1024**3,'seedbonus':420,'seeding':12,'leeching':1,'hit_and_runs':0,'warnings':0,'seeding_size':10*1024**3,'total_uploads':3},'events':[]}
            page.locator('#tracker-save').click()
            expect(page.locator('#tracker-key')).to_have_value('')
            app.extensions['trackers'].refresh()
            page.evaluate('refreshTrackers()')
            expect(page.locator('#tracker-settings-list')).to_contain_text('Forbundet')
            page.locator('#tracker-settings-list').get_by_role('button',name='Rediger').click()
            expect(page.locator('#tracker-key')).to_have_value('')
            assert page.locator('#tracker-key').get_attribute('required') is None
            page.locator('#tracker-name').fill('Min NordicBytes-konto')
            page.locator('#tracker-save').click()
            expect(page.locator('#tracker-settings-list')).to_contain_text('Min NordicBytes-konto')
            page.screenshot(path=str(root/'test-results/desktop-trackers.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(root/'test-results/mobile-trackers.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1000})
            page.locator('.nav[href="#torrents"]').click()
            expect(page.locator('#tracker-overview')).to_be_visible()
            expect(page.locator('#tracker-account-list')).to_contain_text('10 GB')
            preview_match={'tracker_id':app.extensions['trackers'].entries()[0]['id'],
                'tracker_name':'Min NordicBytes-konto','size':15*1024**3,'freeleech':100,
                'double_upload':True,'featured':False,'internal':False,'refundable':False}
            app.extensions['trackers'].benefits.request=lambda meta,selected='',priority=0: {'status':'matched','matches':[dict(preview_match)]}
            page.locator('#new-torrent').click()
            page.locator('#magnet').fill('magnet:?xt=urn:btih:'+'b'*40)
            page.locator('#add-save').click()
            expect(page.locator('#add-dialog')).not_to_be_visible()
            expect(page.locator('#ratio-dialog')).to_be_visible()
            expect(page.locator('#preview-benefits')).to_contain_text('100 % Freeleech')
            expect(page.locator('#preview-benefits')).to_contain_text('Dobbelt upload')
            expect(page.locator('#preview-ratio')).to_contain_text('Forventet tracker-ratio: 2')
            expect(page.locator('#preview-ratio .ratio-warning-text')).to_have_count(0)
            preview_match['freeleech']=0
            page.evaluate('loadPreviewBenefits()')
            expect(page.locator('#preview-ratio')).to_contain_text('Forventet tracker-ratio: 0,5')
            expect(page.locator('#preview-ratio [role="alert"]')).to_contain_text('0,5 eller lavere')
            expect(page.locator('#ratio-save')).to_be_enabled()
            page.screenshot(path=str(root/'test-results/desktop-ratio-warning.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(root/'test-results/mobile-ratio-warning.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1000})
            preview_match['freeleech']=100
            page.evaluate('loadPreviewBenefits()')
            expect(page.locator('#preview-ratio .ratio-warning-text')).to_have_count(0)
            app.extensions['runtime'].rpc.assert_not_called()
            page.locator('#ratio-limit').fill('2.5')
            page.screenshot(path=str(root/'test-results/desktop-ratio.png'),full_page=True)
            page.locator('#ratio-save').click()
            expect(page.locator('#ratio-dialog')).not_to_be_visible()
            expect(page.locator('#torrent-list')).to_contain_text('100 % Freeleech')
            assert app.extensions['runtime'].rpc.call_args.args[0]=='add'
            assert set(app.extensions['runtime'].rpc.call_args.args[1])=={'magnet','ratio_limit','ratio_action'}
            assert app.extensions['runtime'].rpc.call_args.args[1]['ratio_limit']==2.5
            assert app.extensions['runtime'].rpc.call_args.args[1]['ratio_action']=='keep'
            page.locator('#new-torrent').click()
            page.locator('#magnet').fill('magnet:?xt=urn:btih:'+'b'*40)
            for width in (1440,390):
                page.set_viewport_size({'width':width,'height':1000})
                page.locator('#method-magnet').click()
                magnet_box=page.locator('#add-dialog').bounding_box()
                page.locator('#method-file').click()
                file_box=page.locator('#add-dialog').bounding_box()
                assert abs(magnet_box['height']-file_box['height'])<1
                assert abs(magnet_box['y']-file_box['y'])<1
            page.screenshot(path=str(root/'test-results/mobile-add-file.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1000})
            page.locator('#method-file').click()
            expect(page.locator('#magnet')).not_to_be_visible()
            page.locator('#torrent-file').set_input_files({'name':'sample.torrent','mimeType':'application/x-bittorrent','buffer':b'd4:infod4:name11:example.iso6:lengthi4eee'})
            page.locator('#add-save').click()
            expect(page.locator('#add-dialog')).not_to_be_visible()
            expect(page.locator('#ratio-dialog')).to_be_visible()
            expect(page.locator('#preview-benefits')).to_contain_text('100 % Freeleech')
            expect(page.locator('#preview-benefits')).to_contain_text('Dobbelt upload')
            page.locator('#ratio-action').select_option('delete')
            expect(page.locator('#ratio-delete-notice')).to_be_visible()
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(root/'test-results/mobile-ratio.png'),full_page=True)
            page.locator('#ratio-save').click()
            expect(page.locator('#ratio-dialog')).not_to_be_visible()
            assert set(app.extensions['runtime'].rpc.call_args.args[1])=={'torrent','ratio_limit','ratio_action'}
            assert app.extensions['runtime'].rpc.call_args.args[1]['ratio_action']=='delete'
            page.set_viewport_size({'width':1440,'height':1000})
            page.get_by_role('button',name='Pause Test Linux ISO').click()
            page.get_by_role('button',name='Fjern Test Linux ISO').click()
            expect(page.get_by_text('Downloadede filer bevares.',exact=False)).to_be_visible()
            page.locator('#delete-dialog .close').click()
            page.locator('.nav[href="#connection"]').click()
            assert page.locator('.country-location img').first.evaluate('(img)=>img.complete && img.naturalWidth>0')
            assert page.locator('.country-location img').first.get_attribute('src')=='/static/flags/ps.svg'
            page.screenshot(path=str(root/'test-results/desktop.png'),full_page=True)
            page.locator('.nav[href="#torrents"]').click()
            expect(page.locator('#downloads-view')).to_be_visible()
            expect(page.locator('#connection')).not_to_be_visible()
            page.screenshot(path=str(root/'test-results/desktop-downloads.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(root/'test-results/mobile.png'),full_page=True)
            page.locator('.nav[href="#connection"]').click()
            expect(page.locator('#connection')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(root/'test-results/mobile-vpn.png'),full_page=True)
            page.emulate_media(reduced_motion='reduce')
            assert page.locator('.flow-link i').first.evaluate("el=>getComputedStyle(el).animationName")=='none'
            page.emulate_media(reduced_motion='no-preference')
            page.locator('#stop').click()
            expect(page.locator('#new-torrent')).to_be_disabled()
            expect(page.locator('#traffic-flow')).to_have_attribute('data-state','blocked')
            assert page.locator('.flow-link i').first.evaluate("el=>getComputedStyle(el).animationName")=='none'
            page.locator('.nav[href="#trackers"]').click()
            page.once('dialog',lambda dialog:dialog.accept())
            page.locator('#tracker-settings-list').get_by_role('button',name='Fjern tracker').click()
            expect(page.locator('#tracker-settings-list')).to_contain_text('Du har ikke tilføjet en tracker endnu.')
            page.locator('.nav[href="#torrents"]').click()
            expect(page.locator('#tracker-overview')).not_to_be_visible()
            assert not errors,errors
            browser.close()
    finally:server.shutdown()
print('PASS: desktop/mobile, login, VPN selection, torrent actions, disabled without VPN')
