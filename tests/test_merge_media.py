"""Track selection, source integrity, publication and real lossless remuxing."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import merge_media as merge
import library_conversion as library


def track(ident, kind, codec, **properties):
    return {'id': ident, 'type': kind, 'codec': codec,
            'properties': {'codec_id': codec, **properties}}


def media(*tracks):
    return {'container': {'recognized': True, 'properties': {'duration': 100_000_000_000}},
            'tracks': list(tracks)}


@pytest.fixture
def films(tmp_path, monkeypatch):
    root = tmp_path/'downloads'; root.mkdir()
    paths = [root/'Main film.mkv', root/'Other film.mkv']
    for index, path in enumerate(paths): path.write_bytes(b'film-'+str(index).encode())
    items = [{'id': library.key(p), 'name': p.name, '_path': str(p), 'size': p.stat().st_size,
              '_row': None, 'job': None, 'torrent_status': 'missing'} for p in paths]
    monkeypatch.setattr(library, 'inventory', lambda api: {'items': items, 'truncated': False})
    videos = [media(track(0, 'video', 'V_MPEGH/ISO/HEVC'), track(2, 'audio', 'A_AC3', audio_channels=6),
                    track(5, 'subtitles', 'S_TEXT/UTF8')),
              media(track(0, 'video', 'V_MPEG4/ISO/AVC'), track(3, 'audio', 'A_EAC3', audio_channels=6),
                    track(8, 'subtitles', 'S_HDMV/PGS'))]
    actual = media(videos[0]['tracks'][0], videos[0]['tracks'][1], *videos[1]['tracks'][1:])
    monkeypatch.setattr(merge, 'identify', lambda path: deepcopy(videos[paths.index(path)] if path in paths else actual))
    monkeypatch.setattr(merge.workflow, 'media_info', lambda path: {'streams': []})
    monkeypatch.setattr(merge.shutil, 'disk_usage', lambda path: SimpleNamespace(free=10**12))
    choices = {'owner': 'alice', 'base': {'id': items[0]['id'], 'fingerprint': library.fingerprint(paths[0]), 'tracks': [2]},
               'donor': {'id': items[1]['id'], 'fingerprint': library.fingerprint(paths[1]), 'tracks': [3, 8]}, 'offset_ms': 250}
    return paths, items, videos, choices


def test_selection_uses_each_files_own_ids_and_preserves_metadata(films):
    paths, items, videos, choices = films
    sources, offset = merge.validate(None, choices)
    args = merge.command(sources, offset, Path('result.mkv'))
    first, second = args[:args.index(str(paths[0]))], args[args.index(str(paths[0]))+1:]
    assert first[-3:] == ['--audio-tracks', '2', '--no-subtitles']
    assert second[-1] == str(paths[1])
    assert '--no-video' in second and '--no-chapters' in second
    assert second[second.index('--audio-tracks')+1] == '3'
    assert second[second.index('--subtitle-tracks')+1] == '8'
    assert '3:250' in second and '8:250' in second
    assert '--no-attachments' not in second  # Keep fonts for copied subtitles.
    assert not any('encode' in a for a in args)


@pytest.mark.parametrize('change', ['same', 'missing', 'boolean', 'duplicate', 'video', 'empty', 'changed', 'offset', 'nan', 'fraction'])
def test_rejects_invalid_or_stale_selection_without_queueing(films, change):
    paths, items, videos, choices = films
    if change == 'same': choices['donor'] = deepcopy(choices['base'])
    if change == 'missing': choices['donor']['id'] = '/etc/passwd'
    if change == 'boolean': choices['donor']['tracks'] = [True]
    if change == 'duplicate': choices['donor']['tracks'] = [3, 3]
    if change == 'video': choices['donor']['tracks'] = [0]
    if change == 'empty': choices['donor']['tracks'] = []
    if change == 'changed': paths[1].write_bytes(b'replaced film')
    if change == 'offset': choices['offset_ms'] = True
    if change == 'nan': choices['offset_ms'] = float('nan')
    if change == 'fraction': choices['offset_ms'] = .5
    with pytest.raises(ValueError): merge.enqueue(None, choices)
    assert merge.read() == []
    assert len(list(paths[0].parent.iterdir())) == 2


def test_kept_and_imported_tracks_can_both_be_subtitle_only(films):
    _, _, _, choices = films
    choices['base']['tracks'] = []; choices['donor']['tracks'] = [8]
    args = merge.command(*merge.validate(None, choices), Path('result.mkv'))
    assert args.count('--no-audio') == 2
    assert '8' in args


def test_details_exposes_joc_profile_and_precise_fingerprint(films, monkeypatch):
    paths, items, _, _ = films
    monkeypatch.setattr(merge.workflow, 'media_info', lambda path: {'streams': [
        {'codec_type': 'audio', 'profile': 'Dolby Digital Plus + Dolby Atmos'}]})
    details = merge.details(None, items[1]['id'])
    assert 'Atmos' in details['tracks'][0]['profile']
    assert details['tracks'][0]['id'] == 3
    assert details['fingerprint'] == [str(v) for v in library.fingerprint(paths[1])]


def test_user_isolation_cancellation_and_retry(films):
    _, _, _, choices = films
    job = merge.enqueue(None, choices)
    assert not merge.jobs_for('bob')['jobs']
    with pytest.raises(ValueError): merge.dispatch(None, 'cancel', {'owner': 'bob', 'id': job['id']})
    merge.update(job['id'], state='error')
    merge.dispatch(None, 'retry', {'owner': 'alice', 'id': job['id']})
    assert merge.read()[0]['state'] == 'queued'
    merge.dispatch(None, 'cancel', {'owner': 'alice', 'id': job['id']})
    merge.tick(None)
    assert merge.read()[0]['state'] == 'cancelled'


def test_queue_revalidates_sources_before_running(films, monkeypatch):
    paths, _, _, choices = films
    merge.enqueue(None, choices); paths[1].write_bytes(b'changed')
    run = Mock(); monkeypatch.setattr(merge.subprocess, 'run', run)
    merge.tick(None)
    assert merge.read()[0]['state'] == 'error'
    run.assert_not_called()


def test_recovery_after_publication_does_not_remux_or_replace_result(films, monkeypatch):
    paths, _, _, choices = films
    queued = merge.enqueue(None, choices)
    temporary = paths[0].with_name('.fjordseed-merge-'+queued['id']+'.partial')
    temporary.write_bytes(b'finished-before-crash')
    target = paths[0].with_name(queued['output'])
    os.link(temporary, target)
    run = Mock(); monkeypatch.setattr(merge.subprocess, 'run', run)
    merge.tick(None)
    assert merge.read()[0]['state'] == 'done'
    assert target.read_bytes() == b'finished-before-crash'
    assert not temporary.exists()
    run.assert_not_called()


def test_publication_checks_tracks_and_never_overwrites_originals(films, monkeypatch):
    paths, _, _, choices = films
    originals = [p.read_bytes() for p in paths]
    queued = merge.enqueue(None, choices)
    def run(args, **kwargs):
        Path(args[args.index('-o')+1]).write_bytes(b'new-matroska')
        kwargs['stdout'].write('#GUI#progress 100%\n')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(merge.subprocess, 'run', run)
    merge.tick(None)
    job = merge.read()[0]
    assert job['state'] == 'done'
    assert (paths[0].parent/queued['output']).read_bytes() == b'new-matroska'
    assert [p.read_bytes() for p in paths] == originals
    assert not list(paths[0].parent.glob('*.partial'))


@pytest.mark.parametrize('failure', ['tracks', 'source', 'exists', 'tool', 'space'])
def test_failed_merges_leave_inputs_and_existing_results_untouched(films, monkeypatch, failure):
    paths, _, _, choices = films
    queued = merge.enqueue(None, choices)
    target = paths[0].parent/queued['output']
    if failure == 'exists': target.write_bytes(b'existing')
    if failure == 'space': monkeypatch.setattr(merge.shutil, 'disk_usage', lambda path: SimpleNamespace(free=0))
    if failure == 'tracks': monkeypatch.setattr(merge, 'verify', Mock(side_effect=ValueError('Forkerte spor')))
    def run(args, **kwargs):
        Path(args[args.index('-o')+1]).write_bytes(b'partial')
        if failure == 'source': paths[1].write_bytes(b'replaced')
        return SimpleNamespace(returncode=2 if failure == 'tool' else 0)
    monkeypatch.setattr(merge.subprocess, 'run', run)
    merge.tick(None)
    assert merge.read()[0]['state'] == 'error'
    assert paths[0].read_bytes() == b'film-0'
    assert target.read_bytes() == b'existing' if failure == 'exists' else not target.exists()
    assert not list(paths[0].parent.glob('*.partial'))


def test_live_worker_is_not_claimed_twice(films, monkeypatch):
    merge.enqueue(None, films[-1])
    process = Mock(); monkeypatch.setattr(merge, 'process', process)
    with merge.worker_lock() as acquired:
        assert acquired
        merge.tick(None)
    process.assert_not_called()


def test_recover_interrupted_worker_and_report_measured_progress(films, monkeypatch):
    queued = merge.enqueue(None, films[-1])
    merge.update(queued['id'], state='running')
    merge.tick(None)
    assert merge.read()[0]['state'] == 'error'
    merge.update(queued['id'], state='running')
    (merge.folder()/(queued['id']+'.log')).write_text('#GUI#progress 12%\n#GUI#progress 58%\n')
    assert merge.jobs_for('alice')['jobs'][0]['progress'] == 58


def test_merge_api_requires_login_csrf_and_sets_owner_server_side(tmp_path):
    from app import create_app
    from test_app import FakeRuntime, login
    app = create_app(tmp_path/'app', testing=True, runtime_factory=FakeRuntime)
    assert app.test_client().get('/api/merge/library').status_code == 401
    client, headers = login(app)
    runtime = app.extensions['runtime']
    assert client.post('/api/merge/queue', json={}).status_code == 403
    assert client.post('/api/merge/queue', json=[], headers=headers).status_code == 400
    assert client.post('/api/merge/queue', json={'owner': 'forged'}, headers=headers).status_code == 200
    runtime.rpc.assert_called_with('library-merge-queue', {'owner': 'local'})
    runtime.rpc.side_effect = ValueError('Testfejl')
    assert client.get('/api/merge/jobs').json == {'error': 'Testfejl'}


@pytest.mark.skipif(not shutil.which('mkvmerge'), reason='Requires MKVToolNix')
@pytest.mark.parametrize('base_extension', ['mkv', 'mp4'])
def test_real_remux_preserves_video_and_eac3_bytes_metadata_and_subtitles(tmp_path, monkeypatch, base_extension):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError: pytest.skip('Requires FFmpeg')
    root = tmp_path/'downloads'; root.mkdir()
    base, donor = root/('base.'+base_extension), root/'donor.mkv'
    sub = root/'test.srt'; sub.write_text('1\n00:00:00,500 --> 00:00:01,500\nHello fjord\n', encoding='utf-8')
    for path, frequency, codec in ((base, 440, 'ac3'), (donor, 880, 'eac3')):
        args = [ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=24:d=2',
                '-f', 'lavfi', '-i', f'sine=frequency={frequency}:duration=2', '-i', str(sub),
                '-map', '0:v', '-map', '1:a', '-map', '2:s', '-c:v', 'libx264', '-c:a', codec,
                '-c:s', 'mov_text' if path.suffix == '.mp4' else 'srt', '-metadata:s:a:0', 'language=eng', '-metadata:s:a:0', 'title=Test audio',
                '-metadata:s:s:0', 'language=dan', '-disposition:s:0', 'forced', str(path)]
        subprocess.run(args, capture_output=True, check=True)
    items = [{'id': library.key(p), 'name': p.name, '_path': str(p), '_row': None, 'size': p.stat().st_size} for p in (base, donor)]
    monkeypatch.setattr(library, 'inventory', lambda api: {'items': items, 'truncated': False})
    def choice(path, ids): return {'id': library.key(path), 'fingerprint': library.fingerprint(path), 'tracks': ids}
    originals = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (base, donor)]
    queued = merge.enqueue(None, {'owner': 'local', 'base': choice(base, [2]), 'donor': choice(donor, [1, 2]), 'offset_ms': 250})
    merge.tick(None)
    job = merge.read()[0]
    assert job['state'] == 'done', job['detail']
    output = root/queued['output']; actual = merge.identify(output)
    assert sorted(t['type'] for t in actual['tracks']) == ['audio', 'subtitles', 'subtitles', 'video']
    audio = next(t for t in actual['tracks'] if t['type'] == 'audio')
    assert audio['codec'] == 'E-AC-3'
    assert audio['properties']['track_name'] == 'Test audio'
    assert [t['properties']['forced_track'] for t in actual['tracks'] if t['type'] == 'subtitles'] == [
        next(t['properties'].get('forced_track', False) for t in merge.identify(p)['tracks'] if t['type'] == 'subtitles')
        for p in (base, donor)]
    def raw(path, mapping, fmt):
        return subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-map', mapping, '-c', 'copy', '-f', fmt, '-'], capture_output=True, check=True).stdout
    assert raw(base, '0:v:0', 'h264') == raw(output, '0:v:0', 'h264')
    assert raw(donor, '0:a:0', 'eac3') == raw(output, '0:a:0', 'eac3')
    text = subprocess.run([ffmpeg, '-v', 'error', '-i', str(output), '-map', '0:s:1', '-f', 'srt', '-'], capture_output=True, check=True).stdout
    assert b'00:00:00,750 --> 00:00:01,750' in text
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in (base, donor)] == originals
