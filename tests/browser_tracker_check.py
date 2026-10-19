"""Account selection with synthetic keys/stats; no tracker or Docker requests."""
from pathlib import Path
import sys
import tempfile
import threading

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime


with tempfile.TemporaryDirectory() as folder:
    app = create_app(folder, testing=True, runtime_factory=FakeRuntime)
    trackers = app.extensions['trackers']
    trackers.fetch = lambda entry: {'username':entry['provider']+' user','stats':{'ratio':2,'uploaded':4000,'downloaded':2000},'events':[]}
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    output = Path(__file__).resolve().parents[1] / 'test-results'
    output.mkdir(exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width in (1440,390):
                page = browser.new_page(viewport={'width':width,'height':900})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.locator('[name=username]').fill('admin')
                page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
                page.get_by_role('button',name='Log ind').click()
                page.locator('.nav[href="#trackers"]').click()
                trigger = page.locator('#tracker-provider-trigger')
                box = trigger.bounding_box()
                if width > 600:
                    assert abs(box['y'] - page.locator('#tracker-name').bounding_box()['y']) < 2
                trigger.click()
                expect(page.get_by_role('option',name='Sagmire',exact=True)).to_be_visible()
                menu = page.locator('#tracker-provider-options').bounding_box()
                assert menu['x'] >= 0 and menu['x'] + menu['width'] <= width
                assert menu['y'] >= 0 and menu['y'] + menu['height'] <= 900
                page.screenshot(path=str(output/f'tracker-picker-{width}.png'))
                page.keyboard.press('ArrowDown')
                page.keyboard.press('Enter')
                expect(trigger).to_have_text('Sagmire')
                expect(page.locator('#tracker-name')).to_have_value('Sagmire')
                page.locator('#tracker-name').fill('My Sagmire '+str(width))
                trigger.click()
                page.get_by_role('option',name='NordicBytes',exact=True).click()
                expect(page.locator('#tracker-name')).to_have_value('My Sagmire '+str(width))
                trigger.click()
                page.get_by_role('option',name='Sagmire',exact=True).click()
                page.locator('#tracker-key').fill('sagmire-synthetic-test-key')
                page.locator('#tracker-save').click()
                expect(page.locator('#tracker-key')).to_have_value('')
                expect(trigger).to_have_text('NordicBytes')
                trackers.refresh()
                page.evaluate('refreshTrackers()')
                card = page.locator('#tracker-settings-list .tracker-card').filter(has_text='My Sagmire '+str(width))
                expect(card).to_contain_text('sagmire user')
                card.get_by_role('button',name='Rediger',exact=True).click()
                expect(trigger).to_have_text('Sagmire')
                expect(page.locator('#tracker-key')).to_have_value('')
                page.locator('#tracker-save').click()
                expect(card).to_contain_text('My Sagmire '+str(width))
                assert all(e['provider']=='sagmire' and e['api_key']=='sagmire-synthetic-test-key' for e in trackers.entries())
                trigger.click()
                page.keyboard.press('Escape')
                expect(trigger).to_have_attribute('aria-expanded','false')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert 'sagmire-synthetic-test-key' not in page.locator('body').inner_text()
                assert not errors, errors
                print('PASS tracker custom picker, Sagmire save/edit, name preservation and keyboard', width)
                page.close()
            browser.close()
    finally:
        server.shutdown()
