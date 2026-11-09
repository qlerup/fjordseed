"""Audio offset accuracy, ambiguity, drift, previews and owner-scoped assets."""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock
import wave
import os
import threading
import time

import numpy as np
import pytest

import merge_sync as sync
import merge_media as merge
from merge_checks import Checks
from merge_progress import snapshot
from test_merge_media import films


def signal(seconds=100, seed=123):
    rng = np.random.default_rng(seed)
    count = round(seconds*sync.RATE)
    values = rng.normal(0, .12, count)
    # Uneven bursts make a recognisable, nonperiodic sound envelope.
    strength = np.repeat(rng.uniform(.08, 1, count//800+1), 800)[:count]
    return np.convolve(values, [.2, .6, .2], mode='same')*strength


@pytest.mark.parametrize('delay', [0, 0.437, -1.251, 3.237])
def test_cross_correlation_finds_same_sound_despite_gain_noise_and_polarity(delay):
    audio = signal(20)
    start = 5*sync.RATE
    reference = audio[start:start+4*sync.RATE]
    search = np.zeros(24*sync.RATE)
    position = start+round(delay*sync.RATE)
    search[position:position+len(reference)] = -.35*reference
    search += np.random.default_rng(4).normal(0, .0001, len(search))
    match = sync.correlate(reference, search)
    assert match['trusted']
    assert abs(match['sample']/sync.RATE-(5+delay)) <= .00025
    assert match['score'] > .98


def test_silence_unrelated_sound_and_periodic_tones_are_not_confident_matches():
    assert sync.correlate(np.zeros(sync.RATE*3), signal(10)) is None
    assert not sync.correlate(signal(3, 7), signal(12, 8))['trusted']
    tone = np.sin(np.arange(sync.RATE*12)/sync.RATE*2*np.pi*200)
    assert not sync.correlate(tone[:sync.RATE*3], tone)['trusted']


def mock_pcm(films, monkeypatch, delay=.437, drift=False):
    paths, _, _, choices = films
    base = signal(); donor = np.zeros_like(base)
    if drift:
        for begin, end, value in ((0, 50, .2), (50, 100, 1.)):
            shift = round(value*sync.RATE)
            left = begin*sync.RATE; right = min(end*sync.RATE, len(base)-shift)
            donor[left+shift:right+shift] = base[left:right]
    else:
        shift = round(delay*sync.RATE)
        if shift >= 0: donor[shift:] = base[:len(base)-shift] if shift else base
        else: donor[:shift] = base[-shift:]
    def read(path, track, start, length):
        audio = base if path == paths[0] else donor
        return audio[round(start*sync.RATE):round((start+length)*sync.RATE)]
    monkeypatch.setattr(sync, 'pcm', read)
    return {**choices, 'check_id': 'a'*32, 'base_audio': 2, 'donor_audio': 3}


def test_three_locations_agree_with_correct_merge_sign_and_waveform(films, monkeypatch):
    data = mock_pcm(films, monkeypatch)
    result = sync.run(None, 'analyse', data)
    assert result['reliable']
    assert result['offset_ms'] == -437  # Donor sound is late, so move it earlier.
    assert sum(row['trusted'] for row in result['samples']) >= 2
    assert result['waveform']['rate'] == 100
    assert max(result['waveform']['base']) <= 1
    assert result['waveform']['base_start'] >= 0


def test_different_offsets_across_film_are_reported_as_drift(films, monkeypatch):
    result = sync.run(None, 'analyse', mock_pcm(films, monkeypatch, drift=True))
    assert result['status'] == 'drift' and not result['reliable']
    assert result['spread_ms'] >= 700


def test_analysis_works_without_selecting_import_tracks_and_rejects_wrong_audio_ids(films, monkeypatch):
    data = mock_pcm(films, monkeypatch)
    data['base']['tracks'] = []; data['donor']['tracks'] = []
    assert sync.run(None, 'analyse', data)['reliable']
    with pytest.raises(ValueError, match='sammenligningsspor'):
        sync.run(None, 'analyse', {**data, 'donor_audio': 0})
    with pytest.raises(ValueError): sync.run(None, 'analyse', {**data, 'check_id': '../outside'})


def test_no_match_outside_search_window_and_changed_sources_are_rejected(films, monkeypatch):
    data = mock_pcm(films, monkeypatch)
    result = sync.run(None, 'analyse', {**data, 'offset_ms': 1000000})
    assert not result['reliable'] and result['offset_ms'] is None
    films[0][1].write_bytes(b'changed')
    with pytest.raises(ValueError, match='ændret'): sync.run(None, 'analyse', data)


def test_preview_has_correct_global_times_for_live_offset_adjustment(films, monkeypatch):
    paths, _, _, choices = films
    made = []
    record = lambda source, audio, start, length, target: made.append((source[1], audio, start, length, target.name))
    monkeypatch.setattr(sync, 'clip', record)
    monkeypatch.setattr(sync, 'audio_clip', record)
    data = {**choices, 'check_id': 'b'*32, 'base_audio': 2, 'donor_audio': 3, 'offset_ms': -1500, 'start': 40}
    result = sync.run(None, 'preview', data)
    assert made == [(paths[0], None, 40, 15, 'base.mp4'), (paths[1], 0, 36.5, 25, 'donor.m4a')]
    assert result['base_start']-result['offset_ms']/1000-result['donor_start'] == 5
    assert not result['base_audio'] and result['donor_audio']


def test_preview_cannot_play_a_track_not_selected_for_the_merge(films, monkeypatch):
    video, audio = Mock(), Mock()
    monkeypatch.setattr(sync, 'clip', video); monkeypatch.setattr(sync, 'audio_clip', audio)
    data = {**films[-1], 'check_id': 'f'*32, 'base_audio': 2, 'donor_audio': 3, 'start': 40}
    data['donor']['tracks'] = [8]  # Only a subtitle has been selected for import.
    with pytest.raises(ValueError, match='lydspor fra den anden fil'): sync.run(None, 'preview', data)
    video.assert_not_called(); audio.assert_not_called()


@pytest.mark.parametrize('length', [5, 30, 60, 120])
def test_user_selected_preview_length_is_honoured_and_clamped_at_end(films, monkeypatch, length):
    video, audio = Mock(), Mock()
    monkeypatch.setattr(sync, 'clip', video); monkeypatch.setattr(sync, 'audio_clip', audio)
    data = {**films[-1], 'check_id': 'f'*32, 'base_audio': 2, 'donor_audio': 3, 'start': 40, 'length': length}
    result = sync.run(None, 'preview', data)
    assert result['base_duration'] == min(length, 60)
    assert video.call_args.args[3] == min(length, 60)
    assert audio.call_args.args[3] <= min(length, 60)+10


@pytest.mark.parametrize('length', [0, 4, 121, None, '30', True, 15.5])
def test_invalid_preview_lengths_are_rejected_before_encoding(films, monkeypatch, length):
    video, audio = Mock(), Mock()
    monkeypatch.setattr(sync, 'clip', video); monkeypatch.setattr(sync, 'audio_clip', audio)
    data = {**films[-1], 'check_id': 'f'*32, 'base_audio': 2, 'donor_audio': 3, 'start': 40, 'length': length}
    with pytest.raises(ValueError, match='prøvelængde'): sync.run(None, 'preview', data)
    video.assert_not_called(); audio.assert_not_called()


@pytest.mark.parametrize('start', [-1, float('nan'), float('inf'), True, 100, '10'])
def test_preview_rejects_invalid_time_before_encoding(films, monkeypatch, start):
    encoder = Mock(); monkeypatch.setattr(sync, 'clip', encoder)
    data = {**films[-1], 'check_id': 'c'*32, 'base_audio': 2, 'donor_audio': 3, 'start': start}
    with pytest.raises(ValueError): sync.run(None, 'preview', data)
    encoder.assert_not_called()


def test_checks_queue_is_scoped_and_runs_async_with_progress(tmp_path):
    runtime = Mock()
    manager = Checks(tmp_path, runtime)
    data = {'kind': 'analyse', 'base': {}, 'donor': {}}
    queued = manager.enqueue('alice', data)
    with pytest.raises(ValueError): manager.enqueue('alice', data)
    with pytest.raises(ValueError): manager.status('bob', queued['id'])
    assert runtime.rpc.call_count == 0
    runtime.rpc.return_value = {'kind': 'analyse', 'detail': 'Match fundet', 'offset_ms': 100}
    manager.run_once()
    assert manager.status('alice', queued['id'])['result']['offset_ms'] == 100
    runtime.rpc.assert_called_once_with('library-merge-analyse', {**data, 'check_id': queued['id']})


def test_asset_routes_authenticate_owner_and_support_byte_ranges(tmp_path):
    from app import create_app
    from test_app import FakeRuntime, login
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    client, headers = login(app); manager = app.extensions['merge_checks']
    assert client.post('/api/merge/checks', json={}).status_code == 403
    assert client.post('/api/merge/checks', json=[], headers=headers).status_code == 400
    data = {'kind': 'preview', 'base': {}, 'donor': {}}
    response = client.post('/api/merge/checks', json=data, headers=headers)
    ident = response.json['id']
    manager.update(ident, state='done', result={'kind': 'preview'})
    folder = manager.media/ident; folder.mkdir(parents=True)
    (folder/'base.mp4').write_bytes(b'0123456789')
    (folder/'donor.m4a').write_bytes(b'abcdefghij')
    result = client.get('/api/merge/checks/'+ident+'/base.mp4', headers={'Range': 'bytes=2-5'})
    assert result.status_code == 206 and result.data == b'2345'
    result = client.get('/api/merge/checks/'+ident+'/donor.m4a', headers={'Range': 'bytes=2-5'})
    assert result.status_code == 206 and result.data == b'cdef'
    assert result.mimetype == 'audio/mp4'
    assert client.get('/api/merge/checks/'+ident+'/other.mp4').status_code == 404
    with client.session_transaction() as session: session['hub_uid'] = 77
    assert client.get('/api/merge/checks/'+ident).status_code == 404
    assert client.get('/api/merge/checks/'+ident+'/base.mp4').status_code == 404
    assert client.get('/api/merge/checks/'+ident+'/donor.m4a').status_code == 404


def test_failed_and_interrupted_checks_explain_failure_without_exposing_assets(tmp_path):
    runtime = Mock(); runtime.rpc.side_effect = ValueError('Filmen er ændret')
    manager = Checks(tmp_path, runtime)
    queued = manager.enqueue('local', {'kind': 'preview', 'base': {}, 'donor': {}})
    manager.run_once()
    assert manager.status('local', queued['id'])['detail'] == 'Filmen er ændret'
    with pytest.raises(ValueError): manager.asset('local', queued['id'], 'base.mp4')
    manager.update(queued['id'], state='running')
    manager = Checks(tmp_path, runtime)
    assert manager.status('local', queued['id'])['state'] == 'error'


def telemetry(tmp_path, text, duration=30):
    (tmp_path/'progress.json').write_text(json.dumps({'detail': 'Laver hovedfilens prøveklip', 'stage': 'video',
        'stage_index': 1, 'stage_total': 3, 'progress': None, 'duration': duration,
        'stage_started_at': 100, 'updated_at': 100, 'progress_file': 'video.ffmpeg'}))
    path = tmp_path/'video.ffmpeg'; path.write_text(text)
    os.utime(path, (139, 139))


def test_progress_uses_actual_output_time_and_encode_speed(tmp_path):
    telemetry(tmp_path, 'frame=240\nout_time_us=10000000\nspeed=0.25x\nprogress=continue\n')
    result = snapshot(tmp_path, now=140)
    assert result['progress'] == 33.3
    assert result['processed_seconds'] == 10
    assert result['eta_seconds'] == 80
    assert result['stage_elapsed_seconds'] == 40
    assert result['stage_index'] == 1 and not result['stale']


def test_startup_partial_updates_and_stale_measurements_do_not_invent_an_eta(tmp_path):
    telemetry(tmp_path, 'frame=1\nout_time_us=500000\nspeed=N/A\nprogress=continue\nout_time_us=20000000\n')
    initial = snapshot(tmp_path, now=140)
    assert initial['processed_seconds'] == .5  # Ignore an incomplete FFmpeg packet.
    assert initial['eta_seconds'] is None
    stale = snapshot(tmp_path, now=200)
    assert stale['stale'] and stale['eta_seconds'] is None
    telemetry(tmp_path, 'out_time_us=N/A\nspeed=nanx\nprogress=continue\n')
    missing = snapshot(tmp_path, now=140)
    assert missing['progress'] is None and missing['eta_seconds'] is None


def test_negative_timestamps_are_zero_and_mux_finalization_is_not_claimed_complete(tmp_path):
    telemetry(tmp_path, 'out_time_us=-40000\nspeed=0.1x\nprogress=continue\n')
    assert snapshot(tmp_path, now=140)['progress'] == 0
    telemetry(tmp_path, 'out_time_us=30000000\nspeed=0.1x\nprogress=continue\n')
    result = snapshot(tmp_path, now=140)
    assert result['progress'] == 99 and result['detail'] == 'Færdiggør videofilen'
    assert result['eta_seconds'] is None
    telemetry(tmp_path, 'out_time_us=30000000\nspeed=0.1x\nprogress=end\n')
    assert snapshot(tmp_path, now=140)['progress'] == 100


def test_status_reports_live_stage_and_freezes_elapsed_time_after_completion(tmp_path, monkeypatch):
    manager = Checks(tmp_path, Mock())
    queued = manager.enqueue('local', {'kind': 'preview', 'base': {}, 'donor': {}})
    manager.update(queued['id'], state='running', started_at=100)
    folder = manager.media/queued['id']; folder.mkdir(parents=True)
    telemetry(folder, 'out_time_us=10000000\nspeed=0.25x\nprogress=continue\n')
    monkeypatch.setattr(time, 'time', lambda: 140)
    result = manager.status('local', queued['id'])
    assert result['progress'] == 33.3 and result['elapsed_seconds'] == 40
    manager.update(queued['id'], state='done', result={'kind': 'preview'})
    monkeypatch.setattr(time, 'time', lambda: 500)
    assert manager.status('local', queued['id'])['elapsed_seconds'] == 40
    assert manager.status('local', queued['id'])['progress'] == 100


@pytest.fixture
def ffmpeg_tools(monkeypatch):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    run = subprocess.run
    def tools(args, **kwargs):
        if args[0] == 'ffmpeg': args = [ffmpeg, *args[1:]]
        return run(args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', tools)
    return ffmpeg


def test_ffmpeg_publishes_measured_progress_while_encoding(tmp_path, ffmpeg_tools):
    target = tmp_path/'preview.mp4'; errors = []
    def work():
        try:
            sync.encode(['ffmpeg', '-nostdin', '-v', 'error', '-re', '-f', 'lavfi', '-i', 'testsrc2=s=64x64:r=24:d=4',
                         '-an', '-c:v', 'libx264', '-threads', '2', str(target)], target, 15, 'video', 4)
        except Exception as exc: errors.append(exc)
    thread = threading.Thread(target=work); thread.start(); seen = []
    try:
        deadline = time.monotonic()+10
        while thread.is_alive() and time.monotonic() < deadline:
            sample = snapshot(tmp_path)
            if isinstance(sample.get('progress'), (int, float)): seen.append(sample['progress'])
            time.sleep(.05)
    finally: thread.join(timeout=20)
    assert not thread.is_alive() and not errors
    assert any(0 < value < 100 for value in seen), seen
    assert snapshot(tmp_path)['progress'] == 100


@pytest.mark.skipif(not shutil.which('mkvmerge'), reason='Requires MKVToolNix')
def test_real_lossy_audio_match_and_seekable_preview_clips(tmp_path, monkeypatch, ffmpeg_tools):
    ffmpeg = ffmpeg_tools
    root = tmp_path/'downloads'; root.mkdir()
    base = signal(40)
    shift = round(.437*sync.RATE); donor = np.concatenate((np.zeros(shift), base))[:len(base)]
    paths = [root/'base.mkv', root/'donor.mkv']
    for path, samples, codec in zip(paths, (base, donor), ('ac3', 'eac3')):
        audio = path.with_suffix('.wav')
        with wave.open(str(audio), 'wb') as handle:
            handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(sync.RATE)
            handle.writeframes((samples*32767).astype('<i2').tobytes())
        subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=s=64x64:r=24:d=40', '-i', str(audio),
                        '-c:v', 'libx264', '-c:a', codec, '-ar', '48000', str(path)], capture_output=True, check=True)
    items = [{'id': merge.library.key(p), 'name': p.name, '_path': str(p), '_row': None, 'size': p.stat().st_size} for p in paths]
    monkeypatch.setattr(merge.library, 'inventory', lambda api: {'items': items, 'truncated': False})
    monkeypatch.setattr(merge.workflow, 'media_info', lambda p: {'streams': [{'codec_type': 'video'}]})
    def choice(p): return {'id': merge.library.key(p), 'fingerprint': merge.library.fingerprint(p), 'tracks': []}
    data = {'check_id': 'd'*32, 'base': choice(paths[0]), 'donor': choice(paths[1]), 'base_audio': 1, 'donor_audio': 1, 'offset_ms': 0}
    result = sync.run(None, 'analyse', data)
    assert result['reliable'], result
    assert abs(result['offset_ms']+437) <= 5, result
    preview = sync.run(None, 'preview', {**data, 'donor': {**data['donor'], 'tracks': [1]}, 'check_id': 'e'*32, 'offset_ms': result['offset_ms'], 'start': 10})
    directory = merge.storage.CONFIG/'merge-previews'/('e'*32)
    assert all((directory/name).stat().st_size > 1000 for name in sync.ASSETS)
    assert [t['type'] for t in merge.identify(directory/'base.mp4')['tracks']] == ['video']
    first = sync.pcm(paths[0], 0, preview['base_start'], 4)
    second = sync.pcm(directory/'donor.m4a', 0, 5, 5)
    match = sync.correlate(first, second)
    assert match['score'] > .8
    assert match['sample']/sync.RATE < .02
    assert preview['donor_start'] == pytest.approx(5-result['offset_ms']/1000)
    assert not list(root.glob('*.merged-*.mkv'))


@pytest.mark.skipif(not shutil.which('mkvmerge'), reason='Requires MKVToolNix')
@pytest.mark.parametrize('size,expected', [('64x64', '64x64'), ('3840x2160', '1920x1080')])
def test_hdr_preview_is_browser_compatible_sdr_without_changing_original(tmp_path, monkeypatch, ffmpeg_tools, size, expected):
    source = tmp_path/'hdr.mkv'; target = tmp_path/'preview.mp4'
    subprocess.run([ffmpeg_tools, '-v', 'error', '-f', 'lavfi', '-i', f'color=s={size}:r=4:d=1',
                    '-vf', 'format=yuv420p10le', '-c:v', 'libx265', '-threads', '1', '-pix_fmt', 'yuv420p10le',
                    '-x265-params', 'log-level=error:pools=1:frame-threads=1:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc',
                    str(source)], capture_output=True, check=True)
    original = source.read_bytes()
    monkeypatch.setattr(merge.workflow, 'media_info', lambda path: {'streams': [{'codec_type': 'video', 'color_transfer': 'smpte2084'}]})
    sync.clip(({}, source, {}, []), None, .25, .5, target)
    result = subprocess.run([ffmpeg_tools, '-hide_banner', '-i', str(target)], capture_output=True, text=True)
    assert 'bt709' in result.stderr and 'yuv420p(' in result.stderr
    assert 'yuv420p10le' not in result.stderr
    assert source.read_bytes() == original
    assert expected in result.stderr  # Preserve small sources and downscale 4K HDR to full HD.


def test_killed_preview_reports_server_resource_failure(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(sync.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a[0], -9, b'', b''))
    with pytest.raises(ValueError, match='hukommelse'):
        sync.encode(['ffmpeg'], tmp_path/'base.mp4', 720, 'video', 15)
    assert 'exit -9' in caplog.text


@pytest.mark.skipif(not shutil.which('mkvmerge'), reason='Requires MKVToolNix')
def test_preview_retains_full_hd_detail_for_visual_sync_checks(tmp_path, monkeypatch, ffmpeg_tools):
    import re
    source = tmp_path/'detailed.mkv'; target = tmp_path/'preview.mp4'
    subprocess.run([ffmpeg_tools, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=1920x1080:r=24:d=1.5',
                    '-c:v', 'ffv1', '-threads', '2', str(source)], capture_output=True, check=True)
    monkeypatch.setattr(merge.workflow, 'media_info', lambda path: {'streams': [{'codec_type': 'video', 'width': 1920, 'height': 1080}]})
    sync.clip(({}, source, {}, []), None, .25, 1, target)
    info = subprocess.run([ffmpeg_tools, '-hide_banner', '-i', str(target)], capture_output=True, text=True)
    assert '1920x1080' in info.stderr
    comparison = subprocess.run([ffmpeg_tools, '-hide_banner', '-i', str(source), '-i', str(target),
        '-filter_complex', '[0:v]trim=start=0.25:duration=1,setpts=PTS-STARTPTS[ref];[1:v]setpts=PTS-STARTPTS[preview];[ref][preview]ssim',
        '-an', '-f', 'null', '-'], capture_output=True, text=True, check=True)
    score = re.search(r'All:([0-9.]+)', comparison.stderr)
    assert score and float(score[1]) > .98, comparison.stderr
