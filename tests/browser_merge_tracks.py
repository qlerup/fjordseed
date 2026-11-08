"""Verify the two-file picker, track payload, failure state and mobile layout."""
from pathlib import Path, PurePosixPath
import sys
import tempfile
import threading
import logging
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime
logging.getLogger('werkzeug').setLevel(logging.ERROR)

artifacts = Path(__file__).resolve().parents[1]/'test-results'/'merge-tracks'
artifacts.mkdir(parents=True, exist_ok=True)
tracks = [
    {'id': 1, 'kind': 'audio', 'codec': 'AC-3', 'language': 'eng', 'channels': 6, 'default': True},
    {'id': 4, 'kind': 'audio', 'codec': 'E-AC-3', 'profile': 'Dolby Digital Plus + Dolby Atmos (JOC)', 'language': 'eng', 'channels': 6},
    {'id': 7, 'kind': 'subtitles', 'codec': 'SubRip/SRT', 'language': 'dan', 'title': 'Dansk'}]
items = [{'id': str(i), 'name': f'Film-{i}-'+('langt-filnavn-'*8)+'.mkv', 'title': f'Film {i}', 'eligible': i != 3, 'size': 20*1024**3,
          'duration': 7200+i*10, 'tracks': tracks, 'fingerprint': ['123456789', '1794171474346797000']} for i in (1, 2, 3)]

class Demo(FakeRuntime):
    host_downloads = PurePosixPath('/downloads')
    def status(self): return {**super().status(), 'enabled': True, 'ready': True}

with tempfile.TemporaryDirectory() as folder:
    app = create_app(folder, testing=True, runtime_factory=Demo)
    server = make_server('127.0.0.1', 0, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors, submitted, jobs = [], [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.route('**/api/conversion/workflow', lambda r: r.fulfill(json={'items': [], 'jobs': []}))
            page.route('**/api/merge/library', lambda r: r.fulfill(json={'items': items, 'truncated': False}))
            page.route('**/api/merge/library/*', lambda r: r.fulfill(json=next(i for i in items if r.request.url.endswith('/'+i['id']))))
            page.route('**/api/merge/jobs', lambda r: r.fulfill(json={'jobs': jobs}))
            def queue(route):
                submitted.append(route.request.post_data_json)
                if len(submitted) == 1:
                    route.fulfill(status=400, json={'error': 'En film er ændret. Vælg filmene igen.'})
                else:
                    jobs.append({'id': 'test', 'name': items[0]['name'], 'state': 'running', 'progress': 58, 'detail': 'Kopierer spor uden genkodning'})
                    route.fulfill(json={'ok': True, 'output': 'Film-1.merged-12345678.mkv'})
            page.route('**/api/merge/queue', queue)
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'initial-login.txt').read_text().strip())
            page.get_by_role('button', name='Log ind', exact=True).click()
            for theme in ('fjord', 'nordic'):
                page.goto(f'http://127.0.0.1:{server.server_port}/#appearance')
                page.locator(f'[name=theme][value={theme}]').check()
                page.locator('#appearance-save').click()
                expect(page.locator('#appearance-status')).to_contain_text('er gemt')
                page.reload()
                page.goto(f'http://127.0.0.1:{server.server_port}/#conversion')
                page.locator('#mt-open').click()
                expect(page.locator('.mt-film')).to_have_count(3)
                expect(page.locator('.mt-film button').nth(2)).to_be_disabled()
                for width in (1440, 390, 320):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (theme, width)
                page.locator('.mt-film button').nth(0).click()
                expect(page.locator('#mt-step-donor')).to_have_attribute('aria-current', 'step')
                expect(page.locator('.mt-film')).to_have_count(2)
                page.locator('#mt-search').fill('Film 2')
                expect(page.locator('.mt-film')).to_have_count(1)
                page.locator('.mt-film button').click()
                expect(page.locator('#mt-form')).to_be_visible()
                expect(page.locator('#mt-duration-warning')).to_be_visible()
                expect(page.locator('#mt-submit')).to_be_disabled()
                base = page.locator('.mt-source').nth(0)
                donor = page.locator('.mt-source').nth(1)
                expect(base.locator('input:checked')).to_have_count(3)
                expect(donor.locator('input:checked')).to_have_count(0)
                base.get_by_label('eng · AC-3', exact=False).uncheck()
                donor.get_by_label('eng · E-AC-3', exact=False).check()
                donor.get_by_label('dan · SubRip/SRT', exact=False).check()
                page.locator('#mt-offset').fill('-1250')
                expect(page.locator('#mt-summary')).to_contain_text('2 lydspor · 2 undertekstspor')
                for width in (1440, 390, 320):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (theme, width, 'tracks')
                    page.screenshot(path=str(artifacts/f'{theme}-tracks-{width}.png'), full_page=True)
                page.locator('#mt-submit').click()
                if len(submitted) == 1:
                    expect(page.locator('#mt-error')).to_contain_text('ændret')
                    expect(page.locator('#mt-form')).to_be_visible()
                    page.locator('#mt-submit').click()
                expect(page.locator('#mt-form')).to_be_hidden()
                expect(page.locator('#mt-jobs')).to_contain_text('58 %')
                assert submitted[-1]['base']['tracks'] == [4, 7]
                assert submitted[-1]['donor']['tracks'] == [4, 7]
                assert submitted[-1]['base']['id'] == '1' and submitted[-1]['donor']['id'] == '2'
                assert submitted[-1]['offset_ms'] == -1250
                assert submitted[-1]['base']['fingerprint'][1] == '1794171474346797000'
                page.locator('#mt-back').click()
                expect(page.locator('#cw-cards')).to_be_visible()
            assert not errors, errors
            browser.close()
            print('PASS: both themes, 1440/390/320px, selection, precise fingerprints, errors, queue and progress')
    finally:
        server.shutdown()
