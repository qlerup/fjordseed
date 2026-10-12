import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import download_storage as ds
from state import State
from storage import Storage
from test_app import login, create_app, FakeRuntime


def row(stage, **changes):
    return {'hash':'a'*40,'progress':1,'state':'stalledUP','share_limit_action':'Stop','save_path':stage,**changes}


def test_only_complete_retained_new_downloads_publish_and_keep_original_destination(tmp_path, monkeypatch):
    stage = ds.prepare(['a'*40], 'film')
    assert Path(stage).parent == tmp_path/'downloads'/ds.BUFFER
    old = ds.read(ds.CONFIG/'download-storage.json', {})['a'*40]
    monkeypatch.setattr(ds,'download_root',lambda:tmp_path/'other')
    assert ds.prepare(['a'*40]) == stage
    assert Path(ds.prepare(['b'*40])).is_relative_to(tmp_path/'other')
    api = Mock()
    assert ds.publish_complete(api,[row(stage,progress=.99),row(stage,share_limit_action='RemoveWithContent'),
        row(stage,state='checkingUP'),row(stage,hash='c'*40)]) == []
    api.assert_not_called()
    assert ds.publish_complete(api,[row(stage)]) == []
    api.assert_called_once_with('torrents/setLocation',{'hashes':'a'*40,'location':old['target']})
    assert Path(old['target']).parent == tmp_path/'downloads'/'film'
    # Only the later completed move is acknowledged, and it is not repeated.
    api.reset_mock()
    ds.publish_complete(api,[row(old['target'],state='moving')])
    assert not ds.read(ds.CONFIG/'download-storage.json',{})['a'*40]['published']
    ds.publish_complete(api,[row(old['target'])])
    assert ds.read(ds.CONFIG/'download-storage.json',{})['a'*40]['published']
    ds.publish_complete(api,[row(old['target'])])
    api.assert_not_called()


def test_publication_does_not_overwrite_and_retries_failed_move(tmp_path):
    stage=ds.prepare(['a'*40])
    target=Path(ds.read(ds.CONFIG/'download-storage.json',{})['a'*40]['target'])
    target.mkdir(parents=True);(target/'existing.mp4').write_text('leave me')
    api=Mock()
    assert ds.publish_complete(api,[row(stage)])
    api.assert_not_called()
    assert (target/'existing.mp4').read_text()=='leave me'
    (target/'existing.mp4').unlink()
    api.side_effect=OSError('offline')
    assert ds.publish_complete(api,[row(stage)])
    assert not ds.read(ds.CONFIG/'download-storage.json',{})['a'*40]['published']
    api.side_effect=None
    assert ds.publish_complete(api,[row(stage)]) == []
    assert api.call_count == 2


def test_removal_retains_files_but_readd_uses_current_destination(tmp_path,monkeypatch):
    stage=Path(ds.prepare(['a'*40,'b'*64]))
    (stage/'movie.mp4').write_bytes(b'keep after manual removal')
    ds.forget(['a'*40])
    assert ds.read(ds.CONFIG/'download-storage.json',{})=={}
    assert (stage/'movie.mp4').exists()
    monkeypatch.setattr(ds,'download_root',lambda:tmp_path/'new')
    assert Path(ds.prepare(['a'*40])).is_relative_to(tmp_path/'new')


def test_rss_cannot_publish_into_reserved_buffer():
    from rss import folder_path
    with pytest.raises(ValueError):folder_path('film/.fjordseed-buffer')


def test_storage_selection_retains_previous_mounts_and_checks_writable(tmp_path):
    r=Mock(state=State(tmp_path),host_downloads=Path('/downloads'))
    storage=Storage(r);storage.helper=Mock(return_value={'ready':True})
    first=storage.select('/mnt/media/film')
    second=storage.select('/mnt/media/series')
    assert first['path']=='/mnt/media/film' and second['path']=='/mnt/media/series'
    assert set(storage.mounts())=={'/mnt/media/film','/mnt/media/series'}
    assert r.stop.call_count==2
    storage.helper.assert_any_call('writable',source='/mnt/media/film')
    storage.publish()
    assert json.loads((tmp_path/'rpc/download-settings.json').read_text())['path'].endswith(second['selected'])
    r.stop.reset_mock();before=r.state.path.read_text()
    storage.helper.side_effect=ValueError('read only')
    with pytest.raises(ValueError):storage.select('/mnt/readonly/movies')
    assert r.state.path.read_text()==before
    r.stop.assert_not_called()


@pytest.mark.parametrize('path',['/etc','/mnt','/mnt/pool/../other','/mnt/pool/.fjordseed-buffer','/srv/a\n','/opt/data',None])
def test_reject_invalid_roots_before_docker(tmp_path,path):
    storage=Storage(Mock(state=State(tmp_path)))
    storage.helper=Mock()
    with pytest.raises(ValueError):storage.select(path)
    storage.helper.assert_not_called()


def test_storage_api_auth_csrf_and_global_admin(tmp_path,monkeypatch):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    app.extensions['runtime'].host_downloads='/downloads'
    assert app.test_client().get('/api/storage').status_code==401
    client,headers=login(app)
    assert client.post('/api/storage',json={'path':'/mnt/media'}).status_code==403
    assert client.get('/api/storage').json['buffer']=='/downloads/.fjordseed-buffer'
    hub=app.extensions['hub'];hub.enabled=True
    hub.current=Mock(return_value={'id':1,'role':'admin','hub_role':'user'})
    with client.session_transaction() as session:session['hub_uid']=1
    assert client.get('/api/storage?browse=1').status_code==403
    hub.current.return_value['hub_role']='admin'
    monkeypatch.setattr(Storage,'select',lambda self,path:{'path':path})
    assert client.post('/api/storage',headers=headers,json={'path':'/mnt/media'}).json['path']=='/mnt/media'
