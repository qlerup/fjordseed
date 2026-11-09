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


def tick(api):
    merge.tick(api)
    # Publication tests acknowledge the independently tested web-side scans.
    for row in merge.read():
        if row['state']=='running' and row.get('phase')=='refresh':
            merge.dispatch(api,'refresh-update',{'id':row['id'],'refresh':{'fjordflix':True,'plex':True},'detail':'Scanned'})


def empty_api(*args, **kwargs):
    return SimpleNamespace(json=lambda: [])


@pytest.fixture(autouse=True)
def archive_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(merge.storage, 'originals_root', lambda: tmp_path/'downloads'/'Originals')
    monkeypatch.setattr(merge.storage, 'seeding_root', lambda: tmp_path/'downloads'/'Seeder')
    monkeypatch.setattr(merge.storage, 'managed_directory', lambda value: Path(value).is_relative_to(tmp_path/'downloads'))


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
    with pytest.raises(ValueError): merge.enqueue(empty_api, choices)
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


@pytest.mark.parametrize('profile,expected', [
    ('Dolby Digital Plus + Dolby Atmos', 'E-AC-3 5.1 + Atmos'),
    ('E-AC-3 JOC', 'E-AC-3 5.1 + Atmos'),
    ('', 'E-AC-3 5.1'),
])
def test_merge_writes_missing_audio_description(films, monkeypatch, profile, expected):
    paths, _, _, choices = films
    monkeypatch.setattr(merge.workflow, 'media_info', lambda path: {'streams': [
        {'codec_type': 'video'},
        {'codec_type': 'audio', 'codec_name': 'eac3', 'profile': profile,
         'channels': 6, 'channel_layout': '5.1(side)'}]})
    args = merge.command(*merge.validate(None, choices), Path('result.mkv'))
    donor = args[args.index(str(paths[0]))+1:args.index(str(paths[1]))]
    assert donor[donor.index('--track-name')+1] == '3:'+expected
    assert [donor[i+1] for i, value in enumerate(donor) if value == '--track-name'] == ['3:'+expected]


def test_merge_preserves_names_and_matches_probe_by_audio_order(films, monkeypatch):
    paths, _, videos, choices = films
    videos[1]['tracks'].insert(1, track(1, 'audio', 'A_AC3', track_name='Commentary'))
    probe = Mock(return_value={'streams': [
        {'codec_type': 'audio', 'tags': {'title': 'Wrong track'}},
        {'codec_type': 'audio', 'tags': {'DESCRIPTION': 'Original Atmos description'}}]})
    monkeypatch.setattr(merge.workflow, 'media_info', probe)
    assert merge.audio_names(paths[1], videos[1], [3]) == {3: 'Original Atmos description'}
    probe.reset_mock()
    assert merge.audio_names(paths[1], videos[1], [1, 8]) == {}
    probe.assert_not_called()


def test_merge_description_falls_back_when_probe_fails(films, monkeypatch):
    paths, _, videos, _ = films
    monkeypatch.setattr(merge.workflow, 'media_info', Mock(side_effect=OSError('ffprobe missing')))
    assert merge.audio_names(paths[1], videos[1], [3, 8]) == {3: 'E-AC-3 6 kanaler'}


def test_user_isolation_cancellation_and_retry(films):
    _, _, _, choices = films
    job = merge.enqueue(empty_api, choices)
    assert not merge.jobs_for('bob')['jobs']
    with pytest.raises(ValueError): merge.dispatch(empty_api, 'cancel', {'owner': 'bob', 'id': job['id']})
    merge.update(job['id'], state='error')
    merge.dispatch(empty_api, 'retry', {'owner': 'alice', 'id': job['id']})
    assert merge.read()[0]['state'] == 'queued'
    merge.dispatch(empty_api, 'cancel', {'owner': 'alice', 'id': job['id']})
    tick(empty_api)
    assert merge.read()[0]['state'] == 'cancelled'


def test_queue_revalidates_sources_before_running(films, monkeypatch):
    paths, _, _, choices = films
    merge.enqueue(empty_api, choices); paths[1].write_bytes(b'changed')
    run = Mock(); monkeypatch.setattr(merge.subprocess, 'run', run)
    tick(empty_api)
    assert merge.read()[0]['state'] == 'error'
    run.assert_not_called()


def test_recovery_after_publication_does_not_remux_or_replace_result(films, monkeypatch):
    paths, _, _, choices = films
    queued = merge.enqueue(empty_api, choices)
    temporary = paths[0].with_name('.fjordseed-merge-'+queued['id']+'.partial')
    temporary.write_bytes(b'finished-before-crash')
    target = paths[0].with_name(queued['output'])
    os.link(temporary, target)
    run = Mock(); monkeypatch.setattr(merge.subprocess, 'run', run)
    tick(empty_api)
    assert merge.read()[0]['state'] == 'done'
    assert target.read_bytes() == b'finished-before-crash'
    assert not temporary.exists()
    run.assert_not_called()


def test_publication_checks_tracks_and_never_overwrites_originals(films, monkeypatch):
    paths, _, _, choices = films
    originals = [p.read_bytes() for p in paths]
    queued = merge.enqueue(empty_api, choices)
    def run(args, **kwargs):
        Path(args[args.index('-o')+1]).write_bytes(b'new-matroska')
        kwargs['stdout'].write('#GUI#progress 100%\n')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(merge.subprocess, 'run', run)
    tick(empty_api)
    job = merge.read()[0]
    assert job['state'] == 'done'
    assert (paths[0].parent/queued['output']).read_bytes() == b'new-matroska'
    assert not paths[0].exists()
    assert (paths[0].parent/'Originals'/paths[0].name).read_bytes() == originals[0]
    assert not paths[1].exists()
    assert (paths[1].parent/'Originals'/paths[1].name).read_bytes() == originals[1]
    assert not list(paths[0].parent.glob('*.partial'))


def test_job_waits_for_both_library_updates_after_original_is_archived(films, monkeypatch):
    paths, _, _, choices = films
    def run(args, **kwargs):
        Path(args[args.index('-o')+1]).write_bytes(b'merged')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(merge.subprocess,'run',run)
    queued=merge.enqueue(empty_api,choices);merge.tick(empty_api)
    assert merge.read()[0]['state']=='running' and merge.read()[0]['phase']=='refresh'
    pending=merge.dispatch(empty_api,'refresh-pending',{})['jobs']
    assert len(pending)==1 and pending[0]['relative']==queued['output']
    assert not paths[0].exists() and paths[0].with_name(queued['output']).exists()
    merge.dispatch(empty_api,'refresh-update',{'id':queued['id'],'refresh':{'fjordflix':True},'detail':'Waiting for Plex'})
    merge.tick(empty_api)  # A restart/worker pass must not remux a published file.
    assert merge.read()[0]['state']=='running'
    merge.dispatch(empty_api,'refresh-update',{'id':queued['id'],'refresh':{'fjordflix':True,'plex':True},'detail':'Done'})
    assert merge.read()[0]['state']=='done'


@pytest.mark.parametrize('failure', ['tracks', 'source', 'exists', 'tool', 'space'])
def test_failed_merges_leave_inputs_and_existing_results_untouched(films, monkeypatch, failure):
    paths, _, _, choices = films
    queued = merge.enqueue(empty_api, choices)
    target = paths[0].parent/queued['output']
    if failure == 'exists': target.write_bytes(b'existing')
    if failure == 'space': monkeypatch.setattr(merge.shutil, 'disk_usage', lambda path: SimpleNamespace(free=0))
    if failure == 'tracks': monkeypatch.setattr(merge, 'verify', Mock(side_effect=ValueError('Forkerte spor')))
    def run(args, **kwargs):
        Path(args[args.index('-o')+1]).write_bytes(b'partial')
        if failure == 'source': paths[1].write_bytes(b'replaced')
        return SimpleNamespace(returncode=2 if failure == 'tool' else 0)
    monkeypatch.setattr(merge.subprocess, 'run', run)
    tick(empty_api)
    assert merge.read()[0]['state'] == 'error'
    assert paths[0].read_bytes() == b'film-0'
    assert target.read_bytes() == b'existing' if failure == 'exists' else not target.exists()
    assert not list(paths[0].parent.glob('*.partial'))


def test_live_worker_is_not_claimed_twice(films, monkeypatch):
    merge.enqueue(empty_api, films[-1])
    process = Mock(); monkeypatch.setattr(merge, 'process', process)
    with merge.worker_lock() as acquired:
        assert acquired
        tick(empty_api)
    process.assert_not_called()


@pytest.fixture
def seeding_merge(films, monkeypatch):
    paths, items, _, choices = films
    companion = paths[0].with_name('cover.txt'); companion.write_bytes(b'original-cover')
    row = {'hash':'a'*40, 'name':'Main film', 'save_path':str(paths[0].parent),
           'progress':1, 'state':'uploading', 'auto_tmm':True}
    items[0]['_row'] = row; items[0]['torrent_status'] = 'linked'
    entries = [{'name':p.name,'size':p.stat().st_size,'priority':1} for p in (paths[0],companion)]
    calls = []; extra_rows = []
    def api(endpoint, data=None):
        calls.append((endpoint, data))
        if endpoint == 'torrents/info': return SimpleNamespace(json=lambda:deepcopy([row,*extra_rows]))
        if endpoint.startswith('torrents/files?'): return SimpleNamespace(json=lambda:deepcopy(entries))
        if endpoint == 'torrents/stop': row['state']='stoppedUP'
        if endpoint == 'torrents/start': row['state']='uploading'
        return SimpleNamespace(json=lambda:[])
    def run(args, **kwargs):
        Path(args[args.index('-o')+1]).write_bytes(b'verified-merged-mkv')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(merge.subprocess, 'run', run)
    def complete_move():
        location = next(data['location'] for endpoint,data in calls if endpoint=='torrents/setLocation')
        for entry in entries:
            source = Path(row['save_path'])/entry['name']; target = Path(location)/entry['name']
            target.parent.mkdir(parents=True,exist_ok=True); source.rename(target)
        row['save_path'] = location; row['state'] = 'stoppedUP'
    return paths, choices, api, row, calls, complete_move, extra_rows


def test_seeding_original_moves_via_qbittorrent_before_library_publication(seeding_merge):
    paths, choices, api, row, calls, moved, _ = seeding_merge
    queued = merge.enqueue(api, choices); tick(api)
    target = paths[0].with_name(queued['output'])
    assert merge.read()[0]['phase']=='finalizing' and merge.read()[0]['state']=='running'
    assert not target.exists() and paths[0].exists()
    assert any(endpoint=='torrents/setLocation' for endpoint,_ in calls)
    assert any(endpoint=='torrents/setAutoManagement' for endpoint,_ in calls)
    tick(api)  # Native relocation is asynchronous: wait for confirmation.
    assert not target.exists() and sum(e=='torrents/setLocation' for e,_ in calls)==1
    moved(); tick(api)
    assert merge.read()[0]['state']=='done'
    assert target.read_bytes()==b'verified-merged-mkv' and not paths[0].exists()
    assert (Path(row['save_path'])/paths[0].name).read_bytes()==b'film-0'
    assert paths[0].with_name('cover.txt').read_bytes()==b'original-cover'
    assert (Path(row['save_path'])/'cover.txt').read_bytes()==b'original-cover'
    assert not paths[1].exists()
    assert (paths[1].parent/'Originals'/paths[1].name).read_bytes()==b'film-1'
    assert row['state']=='uploading' and any(e=='torrents/start' for e,_ in calls)
    records = merge.storage.read(merge.storage.CONFIG/'download-storage.json', {})
    assert records[row['hash']]['library_replaced'] is True


def test_paused_original_stays_paused_and_finalization_recovers_without_remux(seeding_merge, monkeypatch):
    paths, choices, api, row, calls, moved, _ = seeding_merge
    row['state']='stoppedUP'
    queued = merge.enqueue(api, choices); tick(api)
    # A restart after handoff must recover from the durable publisher receipt.
    merge.update(queued['id'], phase=None)
    moved()
    monkeypatch.setattr(merge.subprocess,'run',Mock(side_effect=AssertionError('Must not remux again')))
    tick(api)
    assert merge.read()[0]['state']=='done'
    assert not any(e=='torrents/start' for e,_ in calls) and row['state']=='stoppedUP'


def test_move_error_can_resume_after_original_path_disappears(seeding_merge, monkeypatch):
    paths, choices, api, row, calls, moved, _ = seeding_merge
    queued = merge.enqueue(api, choices); tick(api); moved()
    def failed_resume(endpoint,data=None):
        if endpoint=='torrents/start': raise ValueError('Temporarily unavailable')
        return api(endpoint,data)
    tick(failed_resume)
    assert merge.read()[0]['state']=='error' and not paths[0].exists()
    with pytest.raises(ValueError): merge.dispatch(api,'cancel',{'id':queued['id'],'owner':'alice'})
    merge.dispatch(api,'retry',{'id':queued['id'],'owner':'alice'})
    monkeypatch.setattr(merge.subprocess,'run',Mock(side_effect=AssertionError('Must not remux again')))
    tick(api)
    assert merge.read()[0]['state']=='done' and row['state']=='uploading'


def test_shared_torrent_original_is_not_moved_or_replaced(seeding_merge):
    paths, choices, api, row, calls, moved, others = seeding_merge
    queued = merge.enqueue(api,choices)
    others.append({**row,'hash':'b'*40})
    tick(api)
    assert merge.read()[0]['state']=='error'
    assert not any(e=='torrents/setLocation' for e,_ in calls)
    assert paths[0].read_bytes()==b'film-0'
    assert not paths[0].with_name(queued['output']).exists()


@pytest.mark.skipif(os.name=='nt', reason='Cross-disk archive verification uses production Linux file locks')
def test_manual_merge_cross_disk_archive_and_output_are_verified_before_removal(films, monkeypatch):
    import errno
    paths, _, _, choices = films
    real_link = os.link
    def cross_disk(source,target,*args,**kwargs):
        if Path(source).parent != Path(target).parent: raise OSError(errno.EXDEV,'Cross-device link')
        return real_link(source,target,*args,**kwargs)
    monkeypatch.setattr(os,'link',cross_disk)
    def run(args,**kwargs):
        Path(args[args.index('-o')+1]).write_bytes(b'merged')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(merge.subprocess,'run',run)
    queued = merge.enqueue(empty_api,choices); tick(empty_api)
    assert paths[0].exists() and merge.read()[0]['state']=='running'
    publication = merge.storage.read(library.ledger(), {})[queued['id']]
    assert publication['result_verify_required'] is True
    for _ in range(4): tick(empty_api)
    assert merge.read()[0]['state']=='done' and not paths[0].exists()
    assert (paths[0].parent/'Originals'/paths[0].name).read_bytes()==b'film-0'
    assert paths[0].with_name(queued['output']).read_bytes()==b'merged'


def test_recover_interrupted_worker_and_report_measured_progress(films, monkeypatch):
    queued = merge.enqueue(empty_api, films[-1])
    merge.update(queued['id'], state='running')
    tick(empty_api)
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
    queued = merge.enqueue(empty_api, {'owner': 'local', 'base': choice(base, [2]), 'donor': choice(donor, [1, 2]), 'offset_ms': 250})
    tick(empty_api)
    job = merge.read()[0]
    assert job['state'] == 'done', job['detail']
    output = root/queued['output']; actual = merge.identify(output)
    assert sorted(t['type'] for t in actual['tracks']) == ['audio', 'subtitles', 'subtitles', 'video']
    audio = next(t for t in actual['tracks'] if t['type'] == 'audio')
    assert audio['codec'] == 'E-AC-3'
    assert audio['properties']['track_name'] == 'Test audio'
    assert [t['properties']['forced_track'] for t in actual['tracks'] if t['type'] == 'subtitles'] == [
        next(t['properties'].get('forced_track', False) for t in merge.identify(p)['tracks'] if t['type'] == 'subtitles')
        for p in (root/'Originals'/base.name, root/'Originals'/donor.name)]
    def raw(path, mapping, fmt):
        return subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-map', mapping, '-c', 'copy', '-f', fmt, '-'], capture_output=True, check=True).stdout
    archived = root/'Originals'/base.name
    donor = root/'Originals'/donor.name
    assert raw(archived, '0:v:0', 'h264') == raw(output, '0:v:0', 'h264')
    assert raw(donor, '0:a:0', 'eac3') == raw(output, '0:a:0', 'eac3')
    text = subprocess.run([ffmpeg, '-v', 'error', '-i', str(output), '-map', '0:s:1', '-f', 'srt', '-'], capture_output=True, check=True).stdout
    assert b'00:00:00,750 --> 00:00:01,750' in text
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in (archived, donor)] == originals


@pytest.fixture
def donor_torrent(films, monkeypatch):
    paths, items, _, choices = films
    row = {'hash':'d'*40, 'name':'Donor film', 'save_path':str(paths[1].parent),
           'progress':1, 'state':'uploading', 'auto_tmm':True}
    items[1]['_row'] = row; items[1]['torrent_status'] = 'linked'
    entries = [{'name':paths[1].name,'size':paths[1].stat().st_size,'priority':1}]
    calls = []; others = []
    def api(endpoint, data=None):
        calls.append((endpoint, data))
        if endpoint == 'torrents/info': return SimpleNamespace(json=lambda:deepcopy([row,*others]))
        if endpoint.startswith('torrents/files?'): return SimpleNamespace(json=lambda:deepcopy(entries))
        if endpoint == 'torrents/stop': row['state']='stoppedUP'
        if endpoint == 'torrents/start': row['state']='uploading'
        return SimpleNamespace(json=lambda:[])
    def run(args, **kwargs):
        Path(args[args.index('-o')+1]).write_bytes(b'merged')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(merge.subprocess, 'run', run)
    def moved():
        location = next(data['location'] for endpoint,data in calls if endpoint=='torrents/setLocation')
        target = Path(location)/paths[1].name
        target.parent.mkdir(parents=True,exist_ok=True); paths[1].rename(target)
        row['save_path'] = location; row['state'] = 'stoppedUP'
    return paths, choices, api, row, calls, moved, others


@pytest.mark.parametrize('paused', [False, True])
def test_donor_torrent_moves_and_only_merged_film_remains(donor_torrent, monkeypatch, paused):
    paths, choices, api, row, calls, moved, _ = donor_torrent
    if paused: row['state']='stoppedUP'
    queued = merge.enqueue(api, choices); tick(api)
    assert merge.read()[0]['state']=='running'
    assert paths[0].with_name(queued['output']).exists() and paths[1].exists()
    assert merge.dispatch(api,'refresh-pending',{})['jobs']==[]
    tick(api)
    assert sum(e=='torrents/setLocation' for e,_ in calls)==1
    moved()
    # A restart after relocation must only finish cleanup, never remux.
    monkeypatch.setattr(merge.subprocess,'run',Mock(side_effect=AssertionError('remux')))
    tick(api)
    assert merge.read()[0]['state']=='done'
    assert not paths[0].exists() and not paths[1].exists()
    assert (Path(row['save_path'])/paths[1].name).read_bytes()==b'film-1'
    assert (row['state']=='stoppedUP') == paused
    records=merge.storage.read(merge.storage.CONFIG/'download-storage.json',{})
    assert records[row['hash']]['library_replaced'] is True


def test_donor_move_failure_retries_after_source_path_disappears(donor_torrent, monkeypatch):
    paths, choices, api, row, calls, moved, _ = donor_torrent
    queued=merge.enqueue(api, choices); tick(api); moved()
    def failed(endpoint,data=None):
        if endpoint=='torrents/start': raise ValueError('resume failed')
        return api(endpoint,data)
    tick(failed)
    assert merge.read()[0]['state']=='error'
    assert not paths[1].exists()
    merge.dispatch(api,'retry',{'id':queued['id'],'owner':'alice'})
    monkeypatch.setattr(merge.subprocess,'run',Mock(side_effect=AssertionError('remux')))
    tick(api)
    assert merge.read()[0]['state']=='done' and row['state']=='uploading'


def test_donor_ownership_is_rechecked_before_native_move(donor_torrent):
    paths, choices, api, row, calls, _, others = donor_torrent
    merge.enqueue(api,choices)
    others.append({**row,'hash':'e'*40})
    tick(api)
    assert merge.read()[0]['state']=='error'
    assert not any(e=='torrents/setLocation' for e,_ in calls)
    assert paths[1].read_bytes()==b'film-1'


def test_changed_published_result_blocks_donor_cleanup(donor_torrent):
    paths, choices, api, row, calls, moved, _ = donor_torrent
    queued=merge.enqueue(api,choices); tick(api); moved()
    paths[0].with_name(queued['output']).write_bytes(b'changed-result')
    tick(api)
    assert merge.read()[0]['state']=='error'
    assert (Path(row['save_path'])/paths[1].name).exists()
    assert not any(e=='torrents/start' for e,_ in calls)


def test_legacy_merge_keeps_donor(films, monkeypatch):
    paths, _, _, choices=films
    queued=merge.enqueue(empty_api,choices)
    rows=merge.read(); rows[0].pop('relocate_donor'); merge.save(rows)
    def run(args,**kwargs):
        Path(args[args.index('-o')+1]).write_bytes(b'merged')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(merge.subprocess,'run',run)
    tick(empty_api)
    assert merge.read()[0]['state']=='done'
    assert paths[1].read_bytes()==b'film-1'


def test_both_sources_in_one_torrent_are_moved_once(seeding_merge, films):
    paths, choices, api, row, calls, moved, _ = seeding_merge
    _, items, _, _ = films
    items[1]['_row']=row; items[1]['torrent_status']='linked'
    original_api=api
    def shared_api(endpoint,data=None):
        response=original_api(endpoint,data)
        if endpoint.startswith('torrents/files?'):
            return SimpleNamespace(json=lambda:response.json()+[
                {'name':paths[1].name,'size':len(b'film-1'),'priority':1}])
        return response
    queued=merge.enqueue(shared_api,choices); tick(shared_api)
    location=next(d['location'] for e,d in calls if e=='torrents/setLocation')
    moved()
    # Simulate qBittorrent moving the donor companion with the same torrent.
    paths[1].rename(Path(location)/paths[1].name)
    tick(shared_api)
    assert merge.read()[0]['state']=='done'
    assert sum(e=='torrents/setLocation' for e,_ in calls)==1
    assert not paths[0].exists() and not paths[1].exists()
    assert paths[0].with_name(queued['output']).exists()
    assert (Path(location)/paths[1].name).read_bytes()==b'film-1'


def test_changed_donor_archive_collision_preserves_input(films, monkeypatch):
    import merge_sources
    paths, _, _, choices=films
    def run(args,**kwargs):
        Path(args[args.index('-o')+1]).write_bytes(b'merged')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(merge.subprocess,'run',run)
    original_advance=merge_sources.advance
    def collision(api,ident):
        jobs=merge.storage.read(library.ledger(),{})
        archive=Path(jobs[ident]['donor_cleanup']['archive'])
        archive.parent.mkdir(parents=True,exist_ok=True)
        archive.write_bytes(b'someone elses file')
        return original_advance(api,ident)
    monkeypatch.setattr(merge_sources,'advance',collision)
    merge.enqueue(empty_api,choices); tick(empty_api)
    assert merge.read()[0]['state']=='error'
    assert paths[1].read_bytes()==b'film-1'


@pytest.mark.parametrize('key', ['base', 'donor'])
def test_manual_source_can_be_deleted_only_after_verified_publication(films, monkeypatch, key):
    paths, _, _, choices=films
    choices[key]['original']={'disposition':'delete'}
    def run(args,**kwargs):
        assert all(p.exists() for p in paths)
        Path(args[args.index('-o')+1]).write_bytes(b'merged')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(merge.subprocess,'run',run)
    queued=merge.enqueue(empty_api,choices);tick(empty_api)
    assert merge.read()[0]['state']=='done'
    assert paths[0].with_name(queued['output']).exists()
    for index,name in enumerate(('base','donor')):
        assert not paths[index].exists()
        assert (paths[index].parent/'Originals'/paths[index].name).exists() == (name!=key)


@pytest.mark.parametrize('action', ['keep','stop_keep','delete','automatic','delete_ratio','delete_time'])
def test_donor_seeding_dropdown_applies_after_move_and_preserves_progress(donor_torrent, action):
    from green_credit import CreditLedger
    paths,choices,api,row,calls,moved,_=donor_torrent
    row.update(uploaded=500,downloaded=1000,total_size=1000,seeding_time=123)
    choices['donor']['original']={'policy':{'ratio_action':action,'ratio_limit':2.5,'seed_minutes':120}}
    queued=merge.enqueue(api,choices);tick(api)
    assert library.pending(row['hash'])
    assert not any(e=='torrents/setShareLimits' for e,_ in calls)
    moved();tick(api)
    assert merge.read()[0]['state']=='done'
    assert not library.pending(row['hash'])
    limits=next(d for e,d in calls if e=='torrents/setShareLimits')
    assert limits['shareLimitAction']==('Stop' if action in ('keep','stop_keep') else 'RemoveWithContent')
    with CreditLedger().snapshot() as credit:
        entry=credit.entries[row['hash']]
        assert entry['target']==(1 if action in ('stop_keep','delete_time') else 2.5)
        assert entry['ratio_only']==(action=='delete_ratio')
        assert entry['adaptive_seeding']==(action=='automatic')
        assert entry['stop_on_complete']==(action=='stop_keep')
        assert entry['seed_minutes']==(120 if action=='delete_time' else None)


@pytest.mark.parametrize('key', ['base','donor'])
def test_original_choices_are_validated_before_queueing(films,key):
    _,_,_,choices=films
    choices[key]['original']={'policy':{'ratio_action':'delete','ratio_limit':2}}
    with pytest.raises(ValueError,match='uden torrent'): merge.enqueue(empty_api,choices)
    assert not merge.read()


def test_same_torrent_rejects_conflicting_seeding_choices(seeding_merge,films):
    import merge_policy
    _,choices,api,row,_,_,_=seeding_merge
    _,items,_,_=films
    items[1]['_row']=row
    choices['base']['original']={'policy':{'ratio_action':'keep','ratio_limit':1}}
    choices['donor']['original']={'policy':{'ratio_action':'delete_ratio','ratio_limit':2}}
    with pytest.raises(ValueError,match='samme seedingvalg'):
        merge_policy.prepare(merge.validate(api,choices)[0],choices)


def test_torrent_cannot_be_switched_to_direct_deletion(donor_torrent):
    _,choices,api,_,_,_,_=donor_torrent
    choices['donor']['original']={'disposition':'delete'}
    with pytest.raises(ValueError,match='Torrentoriginaler'): merge.enqueue(api,choices)


def test_policy_failure_can_retry_without_merging_or_moving_again(donor_torrent,monkeypatch):
    _,choices,api,row,calls,moved,_=donor_torrent
    choices['donor']['original']={'policy':{'ratio_action':'delete_ratio','ratio_limit':3}}
    queued=merge.enqueue(api,choices);tick(api);moved()
    def failed(endpoint,data=None):
        if endpoint=='torrents/setShareLimits':raise ValueError('temporary API failure')
        return api(endpoint,data)
    tick(failed)
    assert merge.read()[0]['state']=='error' and library.pending(row['hash'])
    merge.dispatch(api,'retry',{'id':queued['id'],'owner':'alice'})
    monkeypatch.setattr(merge.subprocess,'run',Mock(side_effect=AssertionError('remux')))
    tick(api)
    assert merge.read()[0]['state']=='done' and not library.pending(row['hash'])
    assert sum(e=='torrents/setLocation' for e,_ in calls)==1
