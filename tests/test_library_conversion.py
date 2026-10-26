import json
from pathlib import Path
import shutil
from unittest.mock import Mock

import pytest

import download_storage as storage
import library_conversion as library
from conversion import DIRECTORY


@pytest.fixture
def film(tmp_path, monkeypatch):
    root = tmp_path / 'library'
    current = root / 'Movie'
    current.mkdir(parents=True)
    (current / 'film.mp4').write_bytes(b'original video')
    (current / 'film.srt').write_bytes(b'subtitles')
    settings = tmp_path / 'settings.json'
    settings.write_text(json.dumps({'conversion_enabled': True}))
    monkeypatch.setattr(storage, 'SETTINGS', settings)
    monkeypatch.setattr(storage, 'download_root', lambda: root)
    monkeypatch.setattr(storage, 'managed_directory', lambda value: bool(value) and Path(value).is_relative_to(root))
    row = {'hash': 'a' * 40, 'name': 'Movie', 'save_path': str(current),
           'progress': 1, 'state': 'uploading', 'share_limit_action': 'Stop'}
    rows = [row]
    files = [{'name': p.name, 'size': p.stat().st_size, 'priority': 1} for p in current.iterdir()]
    def response(path, data=None):
        if path == 'torrents/info':
            return Mock(json=lambda: rows)
        if path.startswith('torrents/files?hash='):
            return Mock(json=lambda: files)
        return Mock()
    api = Mock(side_effect=response)
    return root, current, row, rows, files, api


def enqueue(film, rate=30):
    root, current, row, rows, files, api = film
    result = library.queue(api, library.key(current / 'film.mp4'), rate)
    return storage.read(library.ledger(), {})[result['id']]


def ready(job):
    work = Path(job['stage']) / DIRECTORY
    result = work / 'result'
    result.mkdir()
    (result / job['output']).write_bytes(b'converted')
    (result / '.fjordseed-converted.json').write_text(json.dumps({'id': job['id'], 'files': [job['output']]}))
    (work / 'status.json').write_text(json.dumps({'id': job['id'], 'state': 'ready'}))


def move_by_qbit(film, job):
    root, current, row, rows, files, api = film
    seed = Path(job['seed'])
    seed.mkdir(parents=True, exist_ok=True)
    for entry in files:
        shutil.move(str(current / entry['name']), str(seed / entry['name']))
    row['save_path'] = str(seed)


@pytest.mark.parametrize('rate', [20, 30, 40])
def test_pc_receives_only_selected_movie_and_original_remains_in_library(film, rate):
    root, current, row, rows, files, api = film
    job = enqueue(film, rate)
    request = storage.read(Path(job['stage']) / DIRECTORY / 'request.json', {})
    assert request['executor'] == 'pc' and request['bitrate'] == rate
    assert request['files'] == [{'name': 'film.mp4', 'size': 14}]
    assert (current / 'film.mp4').read_bytes() == b'original video'
    assert (Path(job['stage']) / 'film.srt').read_bytes() == b'subtitles'
    assert not any(c.args[0] == 'torrents/setLocation' for c in api.call_args_list)
    assert library.pending(row['hash'])


def test_verified_return_then_native_move_then_publication_and_persistent_flag(film):
    root, current, row, rows, files, api = film
    job = enqueue(film)
    assert library.reconcile(api, rows) == []
    assert (current / 'film.mp4').exists()
    ready(job)
    assert library.reconcile(api, rows) == []
    assert api.call_args.args == ('torrents/setLocation', {'hashes': row['hash'], 'location': job['seed']})
    assert (current / 'film.mp4').exists() and not (current / 'film.mkv').exists()
    assert library.reconcile(api, rows) == []
    assert len([c for c in api.call_args_list if c.args[0] == 'torrents/setLocation']) == 1
    move_by_qbit(film, job)
    row['state'] = 'moving'
    assert library.reconcile(api, rows) == []
    assert not (current / 'film.mkv').exists()
    row['state'] = 'uploading'
    assert library.reconcile(api, rows) == []
    assert (current / 'film.mkv').read_bytes() == b'converted'
    assert (current / 'film.srt').read_bytes() == b'subtitles'
    assert (Path(job['seed']) / 'film.mp4').read_bytes() == b'original video'
    assert row['share_limit_action'] == 'Stop'
    assert not library.pending(row['hash'])
    record = storage.read(storage.CONFIG / 'download-storage.json', {})[row['hash']]
    assert record['library_replaced'] and record['published'] and record['stage'] == job['seed']
    assert library.reconcile(api, rows) == []  # Clean temporary hard links only.
    assert not Path(job['stage']).exists()
    item = library.listing(api)['items'][0]
    assert item['name'] == 'Movie/film.mkv' and item['converted']['bitrate'] == 30
    assert item['converted']['converted_at'] > 0 and not item['eligible']
    assert all(not c.args[0].startswith(('torrents/delete', 'torrents/stop', 'torrents/start')) for c in api.call_args_list)


def test_changed_original_blocks_move_and_publication(film):
    root, current, row, rows, files, api = film
    job = enqueue(film)
    ready(job)
    (current / 'film.mp4').write_bytes(b'changed source')
    assert library.reconcile(api, rows)
    assert not any(c.args[0] == 'torrents/setLocation' for c in api.call_args_list)
    assert not (current / 'film.mkv').exists()


def test_collision_after_native_move_is_preserved_and_recovers(film):
    root, current, row, rows, files, api = film
    job = enqueue(film)
    ready(job)
    library.reconcile(api, rows)
    move_by_qbit(film, job)
    (current / 'film.mkv').write_bytes(b'other file')
    assert library.reconcile(api, rows)
    assert (current / 'film.mkv').read_bytes() == b'other file'
    assert (Path(job['seed']) / 'film.mp4').read_bytes() == b'original video'
    (current / 'film.mkv').unlink()
    assert library.reconcile(api, rows) == []
    assert (current / 'film.mkv').read_bytes() == b'converted'


def test_source_shared_by_two_torrents_cannot_be_queued(film):
    root, current, row, rows, files, api = film
    rows.append({**row, 'hash': 'b' * 40})
    assert not library.listing(api)['items'][0]['eligible']
    with pytest.raises(ValueError):
        enqueue(film)


def test_adding_cross_seed_after_queue_blocks_native_move(film):
    root, current, row, rows, files, api = film
    job = enqueue(film)
    ready(job)
    rows.append({**row, 'hash': 'b' * 40})
    assert library.reconcile(api, rows)
    assert not any(c.args[0] == 'torrents/setLocation' for c in api.call_args_list)


def test_cancel_removes_only_disposable_snapshot_and_allows_new_job(film):
    root, current, row, rows, files, api = film
    job = enqueue(film)
    library.cancel(job['id'])
    assert not library.pending(row['hash']) and not Path(job['stage']).exists()
    assert (current / 'film.mp4').read_bytes() == b'original video'
    assert library.listing(api)['jobs'] == []
    assert enqueue(film)['id'] != job['id']


def test_unmanaged_movie_visible_but_disabled_and_hidden_buffers_excluded(film):
    root, current, row, rows, files, api = film
    (root / 'unmanaged.mkv').write_bytes(b'video')
    hidden = root / '.incomplete' / 'seedingmappe'
    hidden.mkdir(parents=True)
    (hidden / 'original.mkv').write_bytes(b'video')
    items = library.listing(api)['items']
    assert {i['name'] for i in items} == {'Movie/film.mp4', 'unmanaged.mkv'}
    assert not next(i for i in items if i['name'] == 'unmanaged.mkv')['eligible']


def test_original_preserved_on_symlink_or_invalid_selection(film):
    root, current, row, rows, files, api = film
    with pytest.raises(ValueError):
        library.queue(api, '../../outside', 30)
    with pytest.raises(ValueError):
        library.queue(api, library.key(current / 'film.mp4'), True)
    assert (current / 'film.mp4').read_bytes() == b'original video'


def test_missing_or_forged_receipt_never_moves_original(film):
    root, current, row, rows, files, api = film
    job = enqueue(film)
    ready(job)
    receipt = Path(job['stage']) / DIRECTORY / 'result' / '.fjordseed-converted.json'
    receipt.write_text(json.dumps({'id': 'b' * 32, 'files': [job['output']]}))
    assert library.reconcile(api, rows)
    assert not any(c.args[0] == 'torrents/setLocation' for c in api.call_args_list)


def test_seed_completion_waits_during_conversion(film):
    from qbit_rpc import finish_seeding
    root, current, row, rows, files, api = film
    enqueue(film)
    api.reset_mock()
    finish_seeding(api, row, {'stop_on_complete': True})
    api.assert_not_called()


def test_keep_policy_still_keeps_original_after_publication_and_does_not_remigrate(film, monkeypatch):
    from qbit_rpc import finish_seeding
    root, current, row, rows, files, api = film
    job = enqueue(film)
    ready(job)
    library.reconcile(api, rows)
    move_by_qbit(film, job)
    library.reconcile(api, rows)
    monkeypatch.setattr(storage, 'retained_library', lambda: str(root))
    api.reset_mock()
    assert storage.publish_complete(api, rows) == []
    api.assert_not_called()
    finish_seeding(api, row, {'stop_on_complete': True})
    assert api.call_args.args == ('torrents/stop', {'hashes': row['hash']})
    assert (Path(job['seed']) / 'film.mp4').exists()
    assert (current / 'film.mkv').exists()


def test_restart_after_partial_publication_finishes_without_overwriting(film):
    root, current, row, rows, files, api = film
    job = enqueue(film)
    ready(job)
    library.reconcile(api, rows)
    move_by_qbit(film, job)
    # A crash after publication of the video but before subtitle/ledger updates.
    import os
    source = Path(job['stage']) / DIRECTORY / 'result' / job['output']
    os.link(source, current / job['output'])
    assert library.reconcile(api, rows) == []
    assert library.converted(current / job['output'])['bitrate'] == 30
    assert (current / 'film.srt').read_bytes() == b'subtitles'


def test_existing_download_conversion_receipt_is_flagged(film):
    root, current, row, rows, files, api = film
    (current / '.fjordseed-converted.json').write_text(json.dumps({
        'id': 'c' * 32, 'files': ['film.mp4'], 'bitrate': 20, 'converted_at': 123}))
    item = library.listing(api)['items'][0]
    assert item['converted'] == {'bitrate': 20, 'converted_at': 123}
    assert not item['eligible']


def test_cross_disk_snapshot_and_publication_are_complete_and_recoverable(film, monkeypatch):
    import errno
    import os
    root, current, row, rows, files, api = film
    real_link = os.link
    def pooled_link(source, target):
        if any(p.startswith('library-') for p in Path(target).parts) or any(
                p.startswith('library-') for p in Path(source).parts):
            raise OSError(errno.EXDEV, 'Synthetic different underlying disk')
        return real_link(source, target)
    monkeypatch.setattr(library.os, 'link', pooled_link)
    job = enqueue(film)
    ready(job)
    library.reconcile(api, rows)
    move_by_qbit(film, job)
    # Crash after the complete video is exclusively linked from a prepared copy.
    source = Path(job['stage']) / DIRECTORY / 'result' / job['output']
    target = current / job['output']
    library.publish_file(job, source, target)
    assert library.reconcile(api, rows) == []
    assert target.read_bytes() == b'converted'
    assert (Path(job['seed']) / 'film.mp4').read_bytes() == b'original video'
    assert library.reconcile(api, rows) == []
    assert not library.scratch(job, target).exists()


def test_preexisting_output_blocks_queue_before_original_is_moved(film):
    root, current, row, rows, files, api = film
    (current / 'film.mkv').write_bytes(b'other film')
    with pytest.raises(ValueError):
        enqueue(film)
    assert not any(c.args[0] == 'torrents/setLocation' for c in api.call_args_list)
    assert (current / 'film.mp4').exists()


def test_explicit_existing_film_choice_is_independent_of_new_download_opt_in(film):
    storage.SETTINGS.write_text(json.dumps({'conversion_enabled': False}))
    assert enqueue(film)['phase'] == 'queued'


def test_verified_windows_report_is_also_recognized(film):
    root, current, row, rows, files, api = film
    (current / 'film.json').write_text(json.dumps({'verified': True,
        'gpu_encoder': 'NVEncC 9.39 HEVC quality', 'video_mbps_target': 40,
        'output': 'C:\\Videos\\film.mp4'}))
    item = library.listing(api)['items'][0]
    assert item['converted']['bitrate'] == 40
    assert not item['eligible']
