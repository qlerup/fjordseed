"""Exercise the single-video preview with imported audio and live timing."""
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
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=24:d=20',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-an', '-movflags', '+faststart', str(clip)], capture_output=True, check=True)
    media = clip.read_bytes()
    audio = Path(folder)/'donor.m4a'
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=880:duration=30',
                    '-c:a', 'aac', '-movflags', '+faststart', str(audio)], capture_output=True, check=True)
    audio_media = audio.read_bytes()
    app = create_app(Path(folder)/'app', testing=True, runtime_factory=Demo)
    server = make_server('127.0.0.1', 0, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.set_default_timeout(10000)
            page.set_default_navigation_timeout(30000)
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
                if check['request']['kind'] == 'preview' and check['polls'] <= 2:
                    percent = 25 if check['polls'] == 1 else 50
                    route.fulfill(json={'id': ident, 'state': 'running', 'detail': 'Laver hovedfilens prøveklip',
                        'progress': percent, 'stage': 'video', 'stage_index': 1, 'stage_total': 3,
                        'processed_seconds': percent/100*check['request']['length'], 'duration': check['request']['length'],
                        'elapsed_seconds': 20 if percent == 25 else 40, 'eta_seconds': 60 if percent == 25 else None,
                        'stale': percent == 50})
                    return
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
                              'base_duration': data['length'], 'donor_duration': data['length']+10, 'offset_ms': data['offset_ms'], 'base_audio': False, 'donor_audio': True, 'video_fps': 24,
                              'detail': 'Prøveklippet er klar'}
                route.fulfill(json={'id': ident, 'state': 'done', 'detail': result['detail'], 'result': result,
                                    'progress': 100, 'elapsed_seconds': 42})
            page.route('**/api/merge/checks', create)
            page.route('**/api/merge/checks/*', status)
            def asset(route):
                body = audio_media if route.request.url.endswith('.m4a') else media
                mime = 'audio/mp4' if route.request.url.endswith('.m4a') else 'video/mp4'
                value = route.request.headers.get('range', '')
                if value.startswith('bytes='):
                    first, last = value[6:].split('-', 1)
                    start = int(first or 0); end = min(len(body)-1, int(last) if last else len(body)-1)
                    route.fulfill(status=206, headers={'Content-Type': mime, 'Accept-Ranges': 'bytes',
                                  'Content-Range': f'bytes {start}-{end}/{len(body)}'}, body=body[start:end+1])
                else: route.fulfill(content_type=mime, headers={'Accept-Ranges': 'bytes'}, body=body)
            page.route('**/api/merge/checks/*/*.mp4', asset)
            page.route('**/api/merge/checks/*/*.m4a', asset)
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
                page.locator('#mt-open').click(); page.locator('#mt-films .mt-film button').nth(0).click()
                expect(page.locator('#mt-dialog')).to_be_visible()
                expect(page.locator('#mt-donor-films .mt-film button')).to_have_count(1)
                page.locator('#mt-donor-films .mt-film button').click()
                expect(page.locator('#ms-preview')).to_be_disabled()
                page.locator('.mt-source').nth(1).locator('input').check()
                page.locator('#mt-next').click()
                expect(page.locator('#mt-sync-step')).to_be_visible()
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
                page.locator('#ms-length').fill('20')
                expect(page.locator('#ms-preview')).to_have_text('Lav 20 sek. prøveklip')
                page.locator('#ms-preview').click()
                expect(page.locator('#ms-preview-work')).to_be_visible()
                expect(page.locator('#ms-preview-progress')).to_have_attribute('value', '25')
                expect(page.locator('#ms-preview-stats')).to_contain_text('5 af 20 sek. video')
                expect(page.locator('#ms-preview-stats')).to_contain_text('Forløbet: 20 sek')
                expect(page.locator('#ms-preview-stats')).to_contain_text('tilbage i dette trin')
                expect(page.locator('#ms-preview-progress')).to_have_attribute('value', '50')
                expect(page.locator('#ms-preview-stats')).to_contain_text('Afventer ny måling')
                expect(page.locator('#ms-preview-stats')).not_to_contain_text('tilbage i dette trin')
                expect(page.locator('#ms-player')).to_be_visible()
                expect(page.locator('#ms-preview-progress')).to_have_attribute('value', '100')
                expect(page.locator('#ms-preview-stats')).to_contain_text('Færdig')
                expect(page.locator('#ms-player video')).to_have_count(1)
                expect(page.locator('#ms-playing-track')).to_contain_text('E-AC-3')
                expect(page.locator('#ms-listen')).to_have_count(0)
                expect(page.locator('#ms-seek')).to_have_attribute('max', '20')
                assert requests[-1]['length'] == 20
                print('Preview received', flush=True)
                page.wait_for_function("()=>document.getElementById('ms-base-video').readyState>=2&&document.getElementById('ms-audio-player').readyState>=2")
                page.locator('#ms-play').click()
                page.wait_for_function("()=>document.getElementById('ms-base-video').currentTime>.3")
                assert page.locator('#ms-base-video').evaluate('(e)=>e.getVideoPlaybackQuality().totalVideoFrames>1')
                try:
                    page.wait_for_function("()=>!document.getElementById('ms-audio-player').paused&&Math.abs(document.getElementById('ms-audio-player').currentTime-document.getElementById('ms-base-video').currentTime-5)<.15")
                except Exception:
                    print(page.evaluate("()=>({status:document.getElementById('ms-player-status').textContent,offset:document.getElementById('mt-offset').value,players:['ms-base-video','ms-audio-player'].map(id=>{const e=document.getElementById(id);return {time:e.currentTime,paused:e.paused,seeking:e.seeking,ready:e.readyState,duration:e.duration,error:e.error?.message};})})"), flush=True)
                    print('Requests:', requests, 'Errors:', errors, flush=True)
                    raise
                print('Playback synchronised', flush=True)
                timing = page.evaluate("(()=>{const a=document.getElementById('ms-base-video'),b=document.getElementById('ms-audio-player');return {difference:b.currentTime-a.currentTime,baseMuted:a.muted,donorMuted:b.muted,donorPaused:b.paused};})()")
                assert abs(timing['difference']-5) < .15, timing
                assert timing['baseMuted'] and not timing['donorMuted'] and not timing['donorPaused'], timing
                page.get_by_role('button', name='+100 ms', exact=True).click()
                page.wait_for_function("()=>Math.abs(document.getElementById('ms-audio-player').currentTime-document.getElementById('ms-base-video').currentTime-4.9)<.15")
                page.locator('#ms-play').click()
                assert page.locator('#ms-audio-player').evaluate('(e)=>e.paused')
                page.locator('#ms-replay').click()
                expect(page.locator('#ms-seek')).to_have_value('0')
                page.get_by_role('button', name='Ét billede frem', exact=True).click()
                page.wait_for_function("()=>Math.abs(document.getElementById('ms-base-video').currentTime-1/24)<.005")
                page.get_by_role('button', name='Ét billede tilbage', exact=True).click()
                page.wait_for_function("()=>document.getElementById('ms-base-video').currentTime<.005")
                if page.evaluate('()=>document.fullscreenEnabled'):
                    page.locator('#ms-fullscreen').click()
                    page.wait_for_function("()=>document.fullscreenElement?.id==='ms-stage'")
                    page.locator('#ms-fullscreen').click()
                    page.wait_for_function('()=>document.fullscreenElement===null')
                for width in (1440, 390, 320):
                    page.set_viewport_size({'width': width, 'height': 1000})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), (theme, width)
                    assert page.locator('#mt-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
                    page.locator('#ms-stage').screenshot(path=str(artifacts/f'{theme}-preview-{width}.png'))
                page.locator('#ms-play').click()
                page.locator('#mt-next').click()
                expect(page.locator('#mt-review-step')).to_be_visible()
                assert page.locator('#ms-audio-player').evaluate('(e)=>e.paused')
                page.locator('#mt-prev').click()
                expect(page.locator('#ms-player')).to_be_visible()
                expect(page.locator('#ms-length')).to_have_value('20')
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
                page.keyboard.press('Escape')
                expect(page.locator('#mt-dialog')).to_be_hidden()
                page.wait_for_function("()=>!document.documentElement.classList.contains('mt-modal-open')")
                page.locator('#mt-back').click()
                assert page.locator('#ms-base-video').evaluate('(e)=>e.paused')
            assert not errors, errors
            assert requests[0]['base_audio'] == 2 and requests[0]['donor_audio'] == 3
            browser.close()
            print('PASS: one video with imported audio, live offset, frame stepping, replay, drift rejection and both themes at 1440/390/320px')
    finally:
        server.shutdown()
