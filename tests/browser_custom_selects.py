"""All dropdown surfaces use custom menus, including dynamic and modal choices."""
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
        return {**super().status(),'profiles':[
            {'id':'a'*32,'name':'Seedbox','desired':True,'relay_enabled':False},
            {'id':'b'*32,'name':'Gateway','desired':True,'relay_enabled':True,'gateway_enabled':True},
            {'id':'c'*32,'name':'Legacy TCP','relay_enabled':True}]}


root=Path(__file__).resolve().parents[1]
(root/'test-results').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as directory:
    app=create_app(directory,testing=True,runtime_factory=Demo)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            for width in (390,1440):
                page=browser.new_page(viewport={'width':width,'height':1000})
                errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.locator('[name=username]').fill('admin')
                page.locator('[name=password]').fill((Path(directory)/'initial-login.txt').read_text().strip())
                page.get_by_role('button',name='Log ind').click()
                page.locator('.nav[href="#connection"]').click()
                expect(page.locator('select:not(.custom-native-select):not(.tracker-native-select)')).to_have_count(0)
                trigger=page.locator('#profile-trigger')
                trigger.click()
                expect(trigger).to_have_attribute('aria-expanded','true')
                expect(page.locator('#profile-options')).to_be_visible()
                expect(page.locator('#profile-options [role=option]').last).to_be_disabled()
                page.keyboard.press('End')
                page.keyboard.press('Enter')
                expect(page.locator('#profile')).to_have_value('b'*32)
                expect(trigger).to_contain_text('Gateway')
                expect(trigger).to_be_focused()
                trigger.click()
                # A normal status refresh must not close or rebuild an unchanged menu.
                page.evaluate('render(current)')
                expect(trigger).to_have_attribute('aria-expanded','true')
                expect(page.locator('#profile-options [aria-selected=true]')).to_be_focused()
                page.keyboard.press('Escape')
                expect(trigger).to_be_focused()
                page.evaluate("document.querySelector('#profile').value=''")
                page.locator('#connect').click()
                expect(trigger).to_have_attribute('aria-invalid','true')
                expect(page.locator('#profile-custom-error')).to_be_visible()
                trigger.click()
                page.get_by_role('option',name='Seedbox · egen torrent-VPN, startet',exact=True).click()
                expect(trigger).not_to_have_attribute('aria-invalid','true')
                page.evaluate("document.querySelector('#profile').disabled=true")
                expect(trigger).to_be_disabled()
                page.evaluate("document.querySelector('#profile').disabled=false")
                for prefix,dialog in [('ratio','ratio-dialog'),('rss','rss-dialog')]:
                    page.evaluate("""({prefix,dialog})=>{
                        document.getElementById(dialog).showModal();
                        if(prefix==='rss')rssShowStep(true);
                        updateSeedingFields(prefix);
                    }""",{'prefix':prefix,'dialog':dialog})
                    menu=page.locator('#'+prefix+'-action-trigger')
                    menu.click()
                    expect(page.locator('#'+prefix+'-action-options')).to_be_visible()
                    assert page.locator('#'+prefix+'-action-options').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
                    page.screenshot(path=str(root/'test-results'/f'custom-{prefix}-{width}.png'))
                    page.get_by_role('option',name='Automatisk: optimer ratio og slet',exact=True).click()
                    expect(page.locator('#'+prefix+'-action')).to_have_value('automatic')
                    expect(page.locator('#'+prefix+'-delete-notice')).to_contain_text('ekstra uploadpotentiale')
                    menu.click();page.keyboard.press('Escape')
                    expect(page.locator('#'+dialog)).to_be_visible()
                    expect(menu).to_be_focused()
                    menu.click();page.keyboard.press('Tab')
                    expect(menu).to_have_attribute('aria-expanded','false')
                    expect(page.locator('#'+prefix+('-limit' if prefix=='ratio' else '-ratio'))).to_be_focused()
                    page.evaluate('(id)=>document.getElementById(id).close()',dialog)
                # Reset and programmatic changes update labels without synthetic change events.
                page.evaluate("document.querySelector('#rss-start').value='7';document.querySelector('#rss-size-unit').value='TB'")
                expect(page.locator('#rss-start-trigger')).to_contain_text('7 dage siden')
                expect(page.locator('#rss-size-unit-trigger')).to_have_text('TB')
                page.evaluate("document.querySelector('#rss-form').reset()")
                expect(page.locator('#rss-start-trigger')).to_have_text('Fra nu')
                expect(page.locator('#rss-size-unit-trigger')).to_have_text('GB')
                page.locator('.nav[href="#streaming"]').click()
                page.evaluate("""() => {
                    document.querySelector('#streaming-folders').hidden=false;
                    const select=document.querySelector('#streaming-library');
                    select.replaceChildren(new Option('/mnt/media/Film','film'),new Option('/mnt/media/Serier','series'));
                    select.value='series';
                }""")
                dynamic=page.locator('#streaming-library-trigger')
                expect(dynamic).to_have_text('/mnt/media/Serier')
                dynamic.click();page.keyboard.press('/')
                page.keyboard.press('Home');page.keyboard.press('Enter')
                expect(page.locator('#streaming-library')).to_have_value('film')
                dynamic.click();page.locator('#page-title').click()
                expect(dynamic).to_have_attribute('aria-expanded','false')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                assert not errors,errors
                page.close()
            browser.close()
    finally:
        server.shutdown()
print('PASS all custom dropdowns, keyboard, validation, disabled choices, modal focus, reset and dynamic options at 390/1440px')
