from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from storage import Storage
from storage_browser import seeder


def test_app_creates_seeder_without_changing_existing_files(tmp_path):
    seeder(tmp_path)
    movie = tmp_path / 'Seeder' / 'original.mkv'
    movie.write_bytes(b'keep original')
    seeder(tmp_path)
    assert movie.read_bytes() == b'keep original'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['Seeder']


def test_existing_file_is_not_replaced(tmp_path):
    (tmp_path / 'Seeder').write_bytes(b'keep')
    with pytest.raises(OSError):
        seeder(tmp_path)
    assert (tmp_path / 'Seeder').read_bytes() == b'keep'


def test_creation_runs_immediately_and_failed_creation_is_retried(monkeypatch):
    clock = [10]
    monkeypatch.setattr('storage.time.monotonic', lambda: clock[0])
    storage = Storage(SimpleNamespace(host_downloads='/media/downloads'))
    storage.helper = Mock(side_effect=[ValueError('offline'), {}, {}])
    with pytest.raises(ValueError):
        storage.ensure_seeder()
    storage.ensure_seeder()
    storage.ensure_seeder()
    assert storage.helper.call_count == 2
    storage.helper.assert_called_with('seeder', source='/media/downloads')
    clock[0] += 61
    storage.ensure_seeder()
    assert storage.helper.call_count == 3
