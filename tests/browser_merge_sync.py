"""Exercise waveform matching, live preview timing and unsafe match rejection."""
from pathlib import Path, PurePosixPath
import json
import logging
import math
import subprocess
import shutil
import sys
import tempfile
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from app import create_app
from test_app import FakeRuntime

logging.getLogger('werkzeug').setLevel(logging.ERROR)
artifacts = Path(__file__).resolve().parents[1]/'test-results'/'merge-sync'
artifacts.mkdir(parents=True, exist_ok=True)
items = [{'id': str(i), 'name': f'Film-{i}.mkv', 'title': f'Film {i}', 'eligible': True,
          'size': 20*1024**3, 'duration': 7200, 'fingerprint': ['1000', '1794171474346797000'],
          'tracks': [{'id': i+1, 'kind': 'audio', 'codec': 'AC-3' if i == 1 else 'E-AC-3', 'language': 'eng', 'channels': 6}]} for i in (1, 2)]

class Demo(FakeRuntime):
    host_downloads = PurePosixPath('/downloads')
    def status(self): return {**super().status(), 'enabled': True, 'ready': True}

with tempfile.TemporaryDirectory() as folder:
    clip = Path(folder)/'preview.mp4'
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=128x72:r=24:d=25',
                    '-f', 'lavfi', '-i', 'sine=frequency=880:duration=25', '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-c:a', 'aac', '-movflags', '+faststart', str(clip)], capture_output=True, check=True)
    media = clip.read_bytes()
    app = create_app(Path(folder)/'app', testing=True, runtime_factory=Demo)
    server = make_server('127.0.0.1', 0, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.set_default_timeout(10000)
            errors, requests = [], []
            checks = {}; scenario = ['matched']
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.route('**/api/conversion/workflow', lambda r: r.fulfill(json={'items': [], 'jobs': []}))
            page.route('**/api/merge/jobs', lambda r: r.fulfill(json={'jobs': []}))
            page.route('**/api/merge/library', lambda r: r.fulfill(json={'items': items, 'truncated': False}))
            page.route('**/api/merge/library/*', lambda r: r.fulfill(json=next(i for i in items if r.request.url.endswith('/'+i['id']))))
            def create(route):
                data = route.request.post_data_json; requests.append(data)
                ident = f'{len(requests):032x}'
                checks[ident] = {'request': data, 'polls': 0, 'scenario': scenario[0]}
                route.fulfill(json={'id': ident, 'state': 'queued'})
            def status(route):
                ident = route.request.url.rsplit('/', 1)[1]; check = checks[ident]
                check['polls'] += 1
                if check['polls'] == 1:
                    route.fulfill(json={'id': ident, 'state': 'running', 'detail': 'Sammenligner lyd · sted 2 af 3', 'progress': 35}); return
                if check['scenario'] == 'error':
                    route.fulfill(json={'id': ident, 'state': 'error', 'detail': 'En film er ændret. Vælg filmene igen.'}); return
                data = check['request']
                if data['kind'] == 'analyse':
                    values = [round(abs(math.sin(i/7)*math.sin(i/43))*.8, 3) for i in range(2000)]
                    result = {'kind': 'analyse', 'status': check['scenario'], 'reliable': check['scenario'] == 'matched',
                              'offset_ms': -437, 'detail': 'Match fundet flere steder' if check['scenario'] == 'matched' else 'Forskydningen ændrer sig gennem filmen.',
                              'samples': [{'time': t, 'offset_ms': shift, 'score': .95, 'trusted': True} for t, shift in ((860, -437), (3600, -437), (6120, -437 if check['scenario'] == 'matched' else -1437))],
                              'waveform': {'rate': 100, 'base_start': 860, 'donor_start': 856.437, 'base': values, 'donor': [0]*400+values+[0]*400}}
                else:
                    result = {'kind': 'preview', 'base_start': data['start'], 'donor_start': data['start']-data['offset_ms']/1000-5,
                              'base_duration': 15, 'donor_duration': 25, 'offset_ms': data['offset_ms'], 'base_audio': True, 'donor_audio': True,
                              'detail': 'Prøveklippet er klar'}
                route.fulfill(json={'id': ident, 'state': 'done', 'detail': result['detail'], 'result': result})
            page.route('**/api/merge/checks', create)
            page.route('**/api/merge/checks/*', status)
            def asset(route):
                value = route.request.headers.get('range', '')
                if value.startswith('bytes='):
                    first, last = value[6:].split('-', 1)
                    start = int(first or 0); end = min(len(media)-1, int(last) if last else len(media)-1)
                    route.fulfill(status=206, headers={'Content-Type': 'video/mp4', 'Accept-Ranges': 'bytes',
                                  'Content-Range': f'bytes {start}-{end}/{len(media)}'}, body=media[start:end+1])
                else: route.fulfill(content_type='video/mp4', headers={'Accept-Ranges': 'bytes'}, body=media)
            page.route('**/api/merge/checks/*/*.mp4', asset)
            page.goto(f'http://127.0.0.1:{server.server_port}')
            page.locator('[name=username]').fill('admin')
            page.locator('[name=password]').fill((Path(folder)/'app/initial-login.txt').read_text().strip())
            page.get_by_role('button', name='Log ind', exact=True).click()
            for theme in ('fjord', 'nordic'):
                print('Checking '+theme, flush=True)
                scenario[0] = 'matched'
                page.goto(f'http://127.0.0.1:{server.server_port}/#appearance')
                page.locator(f'[name=theme][value={theme}]').check(); page.locator('#appearance-save').click()
                expect(page.locator('#appearance-status')).to_contain_text('er gemt'); page.reload()
                page.goto(f'http://127.0.0.1:{server.server_port}/#conversion')
                page.locator('#mt-open').click(); page.locator('.mt-film button').nth(0).click()
                expect(page.locator('.mt-film button')).to_have_count(1)
                page.locator('.mt-film button').click()
                page.locator('.mt-source').nth(1).locator('input').check()
                page.locator('#ms-analyse').click()
                expect(page.locator('#ms-progress')).to_be_visible()
                expect(page.locator('#ms-apply')).to_be_visible()
                expect(page.locator('#ms-verdict')).to_contain_text('-437 ms')
                before = page.locator('#ms-waveform').evaluate('(e)=>e.toDataURL()')
                page.locator('#ms-apply').click()
                expect(page.locator('#mt-offset')).to_have_value('-437')
                after = page.locator('#ms-waveform').evaluate('(e)=>e.toDataURL()')
                assert before != after, 'graph must move when the offset changes'
                page.get_by_role('button', name='+10 ms', exact=True).click()
                expect(page.locator('#mt-offset')).to_have_value('-427')
                page.locator('#ms-preview').click()
                expect(page.locator('#ms-player')).to_be_visible()
                print('Preview received', flush=True)
                page.wait_for_function("()=>document.getElementById('ms-base-video').readyState>=2&&document.getElementById('ms-donor-video').readyState>=2")
                page.locator('#ms-play').click()
                page.wait_for_function("()=>document.getElementById('ms-base-video').currentTime>.3")
                try:
                    page.wait_for_function("()=>!document.getElementById('ms-donor-video').paused&&Math.abs(document.getElementById('ms-donor-video').currentTime-document.getElementById('ms-base-video').currentTime-5)<.15")
                except Exception:
                    print(page.evaluate("()=>({status:document.getElementById('ms-player-status').textContent,offset:document.getElementById('mt-offset').value,videos:['ms-base-video','ms-donor-video'].map(id=>{const e=document.getElementById(id);return {time:e.currentTime,paused:e.paused,seeking:e.seeking,ready:e.readyState,duration:e.duration,error:e.error?.message,seekable:e.seekable.length,src:e.src};})})"), flush=True)
                    print('Requests:', requests, 'Errors:', errors, flush=True)
                    raise
                print('Playback synchronised', flush=True)
                timing = page.evaluate("(()=>{const a=document.getElementById('ms-base-video'),b=document.getElementById('ms-donor-video');return {difference:b.currentTime-a.currentTime,baseMuted:a.muted,donorMuted:b.muted,donorPaused:b.paused};})()")
                assert abs(timing['difference']-5) < .15, timing
                assert timing['baseMuted'] and not timing['donorMuted'] and not timing['donorPaused'], timing
                page.get_by_role('button', name='+100 ms', exact=True).click()
                page.wait_for_function("()=>Math.abs(document.getElementById('ms-donor-video').currentTime-document.getElementById('ms-base-video').currentTime-4.9)<.15")
                page.locator('#ms-listen').select_option('base')
                assert page.locator('#ms-base-video').evaluate('(e)=>!e.muted')
                assert page.locator('#ms-donor-video').evaluate('(e)=>e.muted')
                page.locator('#ms-play').click()
                for width in (1440, 390, 320):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (theme, width)
                    page.locator('#ms-panel').screenshot(path=str(artifacts/f'{theme}-preview-{width}.png'))
                page.locator('#mt-offset').fill('10000'); page.locator('#mt-offset').dispatch_event('input')
                expect(page.locator('#ms-player-status')).to_contain_text('uden for prøveklippet')
                page.locator('#mt-offset').fill('0'); page.locator('#mt-offset').dispatch_event('input')
                scenario[0] = 'drift'; page.locator('#ms-analyse').click()
                expect(page.locator('#ms-verdict')).to_contain_text('ændrer sig')
                expect(page.locator('#ms-apply')).to_be_hidden()
                expect(page.locator('#mt-offset')).to_have_value('0')
                scenario[0] = 'error'; page.locator('#ms-analyse').click()
                expect(page.locator('#ms-error')).to_contain_text('ændret')
                expect(page.locator('#ms-analyse')).to_be_enabled()
                page.locator('#mt-back').click()
                assert page.locator('#ms-base-video').evaluate('(e)=>e.paused')
            assert not errors, errors
            assert requests[0]['base_audio'] == 2 and requests[0]['donor_audio'] == 3
            browser.close()
            print('PASS: waveform/offset, async status, live audio/video sync, drift rejection and both themes at 1440/390/320px')
    finally:
        server.shutdown()
