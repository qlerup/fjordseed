import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
import download_storage as ds
from storage import Storage
from storage_mount import mount_plan
from state import State
from test_app import create_app,FakeRuntime,login


def test_separate_buffer_and_retained_destination_are_captured_per_torrent(tmp_path,monkeypatch):
    buffer=tmp_path/'old-disk';buffer.mkdir()
    retained=tmp_path/'new-disk';retained.mkdir()
    settings=tmp_path/'download-settings.json';settings.write_text(json.dumps({'streaming_enabled':True,'buffer_path':'/downloads'}))
    monkeypatch.setattr(ds,'SETTINGS',settings)
    monkeypatch.setattr(ds,'BUFFER_ROOT',buffer)
    monkeypatch.setattr(ds,'download_root',lambda:retained)
    stage=ds.prepare(['a'*40],folder='Film',name='Movie')
    assert Path(stage).is_relative_to(buffer)
    record=ds.read(ds.CONFIG/'download-storage.json',{})['a'*40]
    assert Path(record['target'])==retained/'Film'/'Movie'
    # A later destination change does not repoint an existing torrent.
    monkeypatch.setattr(ds,'download_root',lambda:tmp_path/'other-disk')
    assert ds.prepare(['a'*40],name='Changed')==stage


def test_destination_selection_never_changes_buffer_mount(tmp_path):
    runtime=Mock(state=State(tmp_path),host_downloads=PurePosixPath('/mnt/old/buffer'))
    storage=Storage(runtime)
    storage.helper=Mock(return_value={'ready':True})
    chosen=storage.select('/mnt/new/kept')
    assert chosen['path']=='/mnt/new/kept'
    assert chosen['buffer']=='/mnt/old/buffer/.incomplete'
    assert runtime.host_downloads==PurePosixPath('/mnt/old/buffer')
    storage.publish()
    settings=json.loads((tmp_path/'rpc/download-settings.json').read_text())
    assert settings['buffer_path']=='/downloads'
    assert settings['path'].endswith(chosen['selected'])


def test_folder_creation_requires_mounted_parent_and_does_not_select_it(tmp_path):
    storage=Storage(Mock(state=State(tmp_path)))
    storage.helper=Mock(side_effect=[{}, {'ready':True}, {'created':True}])
    assert storage.create_folder('/mnt/disk','Film')=={'path':'/mnt/disk/Film'}
    storage.helper.assert_called_with('create','Film',source='/mnt/disk')
    assert storage.settings()['selected']==''
    for name in ('..','a/b','a\\b','.incomplete',' name',''):
        with pytest.raises(ValueError):storage.create_folder('/mnt/disk',name)


def test_mount_guide_uses_discovered_pool_and_fixed_lxc_not_user_paths():
    inventory={'ctid':'1000','storages':[dict(id='media-storagepool1',online=True,type='dir',path='/mnt/pve/media-storagepool1')]}
    plan=mount_plan(inventory,'media-storagepool1')
    assert plan['path']=='/mnt/fjordhub/media-storagepool1/fjordseed'
    assert 'pct set' in plan['commands'] and 'mountpoint -q' in plan['commands']
    assert 'mkfs' not in plan['commands']
    assert 'pct reboot' in plan['commands']
    with pytest.raises(ValueError):mount_plan(inventory,'unknown')
    with pytest.raises(ValueError):mount_plan({**inventory,'ctid':'1000;reboot'},'media-storagepool1')


def test_mount_and_folder_routes_require_login_csrf_and_hub_admin(tmp_path,monkeypatch):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    client=app.test_client()
    assert client.post('/api/storage/folders',json={}).status_code in (401,403)
    client,headers=login(app)
    assert client.post('/api/storage/folders',json={}).status_code==403
    hub=app.extensions['hub'];hub.enabled=True;hub.current=Mock(return_value={'hub_role':'user'})
    assert client.post('/api/storage/mount-plan',headers=headers,json={}).status_code==403
