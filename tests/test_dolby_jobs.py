from pathlib import Path
import pytest
import dolby_backup as b
import dolby_jobs as jobs
from test_dolby_backup import movie,DV


@pytest.fixture
def library(tmp_path,monkeypatch):
    root=tmp_path/'library';root.mkdir()
    monkeypatch.setattr(jobs,'roots',lambda:[root])
    monkeypatch.setattr(jobs,'kick',lambda:None)
    monkeypatch.setattr(b.shutil,'disk_usage',lambda _:type('Usage',(),{'free':10**12})())
    path=root/'Show S01E01.mkv';path.write_bytes(movie());b.suspend(path,DV)
    return root,path


def test_discovery_restore_persistence_and_no_duplicate_jobs(library):
    root,path=library
    listing=jobs.listing();assert len(listing['items'])==1
    item=listing['items'][0];assert item['state']=='available'
    assert 'path' not in item
    jobs.queue(item['id']);jobs.queue(item['id']);jobs.run()
    assert path.read_bytes()==movie()
    result=jobs.listing()['items'][0];assert result['state']=='restored'
    assert result['restored_at']
    jobs.queue(item['id']);jobs.run()
    assert path.read_bytes()==movie()


def test_wrong_file_fails_without_overwrite_and_can_retry(library):
    root,path=library;item=jobs.listing()['items'][0];hdr=path.read_bytes()
    path.write_bytes(hdr+b'changed')
    jobs.queue(item['id']);jobs.run()
    assert jobs.listing()['items'][0]['state']=='error'
    assert path.read_bytes()==hdr+b'changed'
    path.write_bytes(hdr);jobs.queue(item['id']);jobs.run()
    assert path.read_bytes()==movie()


def test_restart_after_atomic_replace_records_success(library):
    root,path=library;item=jobs.listing()['items'][0]
    jobs.queue(item['id'])
    with jobs.locked() as data:data[item['id']]['state']='restoring'
    b.restore(path)  # process dies after replace, before receipt
    jobs.run()
    assert jobs.listing()['items'][0]['state']=='restored'


def test_source_seeders_workfiles_and_symlinks_are_not_discovered(library):
    root,path=library
    for name in ('Seeder','.incomplete','.fjordseed-shared'):
        folder=root/name;folder.mkdir()
        (folder/'film.mkv').write_bytes(movie())
        b.suspend(folder/'film.mkv',DV)
    (root/'link').symlink_to(root/'Seeder',target_is_directory=True)
    assert len(jobs.listing()['items'])==1
    with pytest.raises(ValueError):jobs.queue('../film')


def test_missing_file_reports_error_and_preserves_archive(library):
    root,path=library;item=jobs.listing()['items'][0];path.unlink()
    jobs.queue(item['id']);jobs.run()
    assert jobs.listing()['items'][0]['state']=='error'
    assert b.sidecar(path).exists()
