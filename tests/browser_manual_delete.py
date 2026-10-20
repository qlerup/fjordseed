"""Manual removal choices against a fake client; never deletes real files."""
import sys
import tempfile
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

row = {'hash':'a'*40, 'name':'Test torrent '+('long title '*15), 'state':'stalledUP',
       'progress':1, 'size':1000, 'ratio':1, 'seeding_time':0, 'upspeed':1024,
       'seeding_unlimited':True, 'seeding_requirement_met':True, 'share_limit_action':'Stop'}

class Demo(FakeRuntime):
    def status(self):
        return {**super().status(), 'ready':True, 'torrents':[dict(row)]}

with tempfile.TemporaryDirectory() as folder:
    app = create_app(folder, testing=True, runtime_factory=Demo)
    app.extensions['state'].save('b'*32, True)
    rpc = app.extensions['runtime'].rpc
    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button', name='Log ind').click()
            dialog = page.locator('#delete-dialog')
            for width in (1440, 390):
                page.set_viewport_size({'width':width, 'height':900})
                page.get_by_role('button', name='Fjern '+row['name'], exact=True).click()
                expect(dialog).to_be_visible()
                expect(page.locator('#delete-files')).to_have_value('keep')
                expect(page.locator('#delete-files-trigger')).to_be_focused()
                page.locator('#delete-files-trigger').click()
                page.locator('#delete-files-options').get_by_role('option',name='Torrenten og alle downloadede filer',exact=True).click()
                expect(page.locator('#delete-description')).to_contain_text('permanent')
                assert dialog.evaluate('e=>e.scrollWidth<=e.clientWidth')
                Path('test-results').mkdir(exist_ok=True)
                page.screenshot(path=f'test-results/manual-delete-{width}.png')
                page.get_by_role('button', name='Annuller', exact=True).click()
                rpc.assert_not_called()
            for choice in ('keep', 'delete','files'):
                page.get_by_role('button', name='Fjern '+row['name'], exact=True).click()
                expect(page.locator('#delete-files')).to_have_value('keep')
                page.locator('#delete-files').select_option(choice)
                page.locator('#delete-save').click()
                expect(dialog).not_to_be_visible()
                if choice=='files':
                    assert rpc.call_args.args[0]=='delete-files'
                else:
                    assert rpc.call_args.args[0]=='delete'
                    assert rpc.call_args.args[1]['delete_files'] is (choice=='delete')
            rpc.reset_mock()
            row['seeding_requirement_met'] = False
            page.reload()
            page.get_by_role('button', name='Fjern '+row['name'], exact=True).click()
            expect(page.locator('#delete-warning')).to_be_visible()
            rpc.side_effect = ValueError('Test removal error')
            page.locator('#delete-save').click()
            expect(page.locator('#delete-error')).to_contain_text('Test removal error')
            expect(dialog).to_be_visible()
            expect(page.locator('#delete-save')).to_be_enabled()
            assert rpc.call_args.args[1]['confirm_early_stop'] is True
            page.keyboard.press('Escape')
            expect(dialog).not_to_be_visible()
            row['share_limit_action'] = 'RemoveWithContent'
            page.reload()
            page.get_by_role('button', name='Fjern '+row['name'], exact=True).click()
            expect(page.locator('#delete-choice')).to_be_visible()
            expect(page.locator('#delete-description')).to_contain_text('bevares')
            page.locator('#delete-files').select_option('delete')
            expect(page.locator('#delete-description')).to_contain_text('permanent')
            assert not errors, errors
            browser.close()
            print('PASS: choices, cancel, reset, early warning, errors, keyboard and desktop/mobile layout')
    finally:
        server.shutdown()
