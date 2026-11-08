"""Audio offset accuracy, ambiguity, drift, previews and owner-scoped assets."""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock
import wave

import numpy as np
import pytest

import merge_sync as sync
import merge_media as merge
from merge_checks import Checks
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
    monkeypatch.setattr(sync, 'clip', lambda source, audio, start, length, target: made.append((source[1], audio, start, length, target.name)))
    data = {**choices, 'check_id': 'b'*32, 'base_audio': 2, 'donor_audio': 3, 'offset_ms': -1500, 'start': 40}
    result = sync.run(None, 'preview', data)
    assert made == [(paths[0], 0, 40, 15, 'base.mp4'), (paths[1], 0, 36.5, 25, 'donor.mp4')]
    assert result['base_start']-result['offset_ms']/1000-result['donor_start'] == 5
    assert result['base_audio'] and result['donor_audio']


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
    result = client.get('/api/merge/checks/'+ident+'/base.mp4', headers={'Range': 'bytes=2-5'})
    assert result.status_code == 206 and result.data == b'2345'
    assert client.get('/api/merge/checks/'+ident+'/other.mp4').status_code == 404
    with client.session_transaction() as session: session['hub_uid'] = 77
    assert client.get('/api/merge/checks/'+ident).status_code == 404
    assert client.get('/api/merge/checks/'+ident+'/base.mp4').status_code == 404


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
    preview = sync.run(None, 'preview', {**data, 'check_id': 'e'*32, 'offset_ms': result['offset_ms'], 'start': 10})
    directory = merge.storage.CONFIG/'merge-previews'/('e'*32)
    assert all((directory/name).stat().st_size > 1000 for name in sync.ASSETS)
    first = sync.pcm(directory/'base.mp4', 0, 0, 4)
    second = sync.pcm(directory/'donor.mp4', 0, 5, 5)
    match = sync.correlate(first, second)
    assert match['score'] > .8
    assert match['sample']/sync.RATE < .02
    assert preview['donor_start'] == pytest.approx(5-result['offset_ms']/1000)
    assert not list(root.glob('*.merged-*.mkv'))


@pytest.mark.skipif(not shutil.which('mkvmerge'), reason='Requires MKVToolNix')
def test_hdr_preview_is_browser_compatible_sdr_without_changing_original(tmp_path, monkeypatch, ffmpeg_tools):
    source = tmp_path/'hdr.mkv'; target = tmp_path/'preview.mp4'
    subprocess.run([ffmpeg_tools, '-v', 'error', '-f', 'lavfi', '-i', 'color=s=64x64:r=24:d=3',
                    '-vf', 'format=yuv420p10le', '-c:v', 'libx265', '-pix_fmt', 'yuv420p10le',
                    '-x265-params', 'log-level=error:pools=1:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc',
                    str(source)], capture_output=True, check=True)
    original = source.read_bytes()
    monkeypatch.setattr(merge.workflow, 'media_info', lambda path: {'streams': [{'codec_type': 'video', 'color_transfer': 'smpte2084'}]})
    sync.clip(({}, source, {}, []), None, .25, 2, target)
    result = subprocess.run([ffmpeg_tools, '-hide_banner', '-i', str(target)], capture_output=True, text=True)
    assert 'bt709' in result.stderr and 'yuv420p(' in result.stderr
    assert 'yuv420p10le' not in result.stderr
    assert source.read_bytes() == original
