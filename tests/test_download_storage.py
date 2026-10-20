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


@pytest.mark.parametrize('buffered',[True,False])
def test_named_download_keeps_readable_name_after_publish(tmp_path,monkeypatch,buffered):
    settings=tmp_path/'download-settings.json'
    settings.write_text(json.dumps({'streaming_enabled':buffered}))
    monkeypatch.setattr(ds,'SETTINGS',settings)
    stage=ds.prepare(['a'*40],'Serier',name='The.Show.S01E02.1080p')
    record=ds.read(ds.CONFIG/'download-storage.json',{})['a'*40]
    assert Path(stage).name=='The.Show.S01E02.1080p'
    assert Path(record['target'])==tmp_path/'downloads'/'Serier'/'The.Show.S01E02.1080p'
    api=Mock()
    assert ds.publish_complete(api,[row(stage)])==[]
    if buffered:
        api.assert_called_once_with('torrents/setLocation',{'hashes':'a'*40,'location':record['target']})
    else:api.assert_not_called()
    assert ds.publish_complete(api,[row(record['target'])])==[]
    assert ds.read(ds.CONFIG/'download-storage.json',{})['a'*40]['published']


def test_name_collision_includes_reserved_destinations_and_preserves_files(tmp_path):
    first=ds.prepare(['a'*40],name='Show')
    second=ds.prepare(['b'*40],name='Show')
    assert Path(first).name=='Show'
    assert Path(second).name.startswith('Show-') and len(Path(second).name)==13
    target=tmp_path/'downloads'/'Existing'
    target.mkdir();(target/'keep.txt').write_text('keep')
    third=ds.prepare(['c'*40],name='Existing')
    assert Path(third).name.startswith('Existing-')
    assert (target/'keep.txt').read_text()=='keep'
    assert ds.prepare(['a'*40],name='Changed name')==first


def test_existing_uuid_records_are_not_renamed(tmp_path):
    old={'stage':str(tmp_path/'downloads'/ds.BUFFER/('a'*32)),
         'target':str(tmp_path/'downloads'/('a'*32)),'published':True}
    with ds.transaction() as entries:entries['b'*40]=old
    assert ds.prepare(['b'*40],name='Readable name')==old['stage']
    assert ds.read(ds.CONFIG/'download-storage.json',{})['b'*40]==old


@pytest.mark.parametrize('name',['../../outside','a/b\\c:bad?*<>|"','..','.fjordseed-buffer','CON','NUL.txt','a\x00\nb','\u00e6'*200,''])
def test_untrusted_torrent_name_is_one_safe_bounded_component(tmp_path,name):
    stage=Path(ds.prepare(['a'*40],name=name))
    assert stage.parent==tmp_path/'downloads'/ds.BUFFER
    assert stage.name not in ('.','..',ds.BUFFER)
    assert not stage.name.startswith('.')
    assert not any(c in stage.name for c in '/\\<>:"|?*\x00\n')
    assert len(stage.name.encode('utf-8'))<=170


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
    marker = Path(old['target']) / ds.PUBLISHING_MARKER
    assert marker.is_file()
    # Only the later completed move is acknowledged, and it is not repeated.
    api.reset_mock()
    ds.publish_complete(api,[row(old['target'],state='moving')])
    assert marker.exists()
    assert not ds.read(ds.CONFIG/'download-storage.json',{})['a'*40]['published']
    ds.publish_complete(api,[row(old['target'])])
    assert ds.read(ds.CONFIG/'download-storage.json',{})['a'*40]['published']
    assert not marker.exists()
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


def test_failed_marker_removal_keeps_publication_pending_for_retry(tmp_path, monkeypatch):
    stage = ds.prepare(['a'*40])
    target = Path(ds.read(ds.CONFIG/'download-storage.json', {})['a'*40]['target'])
    api = Mock()
    assert ds.publish_complete(api, [row(stage)]) == []
    original = Path.unlink
    def fail_marker(path, *args, **kwargs):
        if path.name == ds.PUBLISHING_MARKER:
            raise PermissionError('read only')
        return original(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', fail_marker)
        assert ds.publish_complete(api, [row(str(target))])
    assert not ds.read(ds.CONFIG/'download-storage.json', {})['a'*40]['published']
    assert (target / ds.PUBLISHING_MARKER).exists()
    assert ds.publish_complete(api, [row(str(target))]) == []
    assert ds.read(ds.CONFIG/'download-storage.json', {})['a'*40]['published']


def test_removal_retains_files_but_readd_uses_current_destination(tmp_path,monkeypatch):
    stage=Path(ds.prepare(['a'*40,'b'*64]))
    (stage/'movie.mp4').write_bytes(b'keep after manual removal')
    ds.forget(['a'*40])
    assert ds.read(ds.CONFIG/'download-storage.json',{})=={}
    assert (stage/'movie.mp4').exists()
    monkeypatch.setattr(ds,'download_root',lambda:tmp_path/'new')
    assert Path(ds.prepare(['a'*40])).is_relative_to(tmp_path/'new')


@pytest.mark.parametrize('buffer_name',['.incomplete','.fjordseed-buffer'])
def test_rss_cannot_publish_into_reserved_buffer(buffer_name):
    from rss import folder_path
    with pytest.raises(ValueError):folder_path('film/'+buffer_name)


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


@pytest.mark.parametrize('path',['/etc','/mnt','/mnt/pool/../other','/mnt/pool/.fjordseed-buffer','/mnt/pool/.incomplete','/srv/a\n','/opt/data',None])
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
    assert client.get('/api/storage').json['buffer']=='/downloads/.incomplete'
    hub=app.extensions['hub'];hub.enabled=True
    hub.current=Mock(return_value={'id':1,'role':'admin','hub_role':'user'})
    with client.session_transaction() as session:session['hub_uid']=1
    assert client.get('/api/storage?browse=1').status_code==403
    hub.current.return_value['hub_role']='admin'
    assert client.post('/api/streaming',headers=headers,json={'enabled':False}).status_code==200
    monkeypatch.setattr(Storage,'select',lambda self,path:{'path':path})
    assert client.post('/api/storage',headers=headers,json={'path':'/mnt/media'}).json['path']=='/mnt/media'


def test_storage_integration_rejection_does_not_expire_valid_login(tmp_path):
    from hub import HubError
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    app.extensions['runtime'].host_downloads='/downloads'
    client,_=login(app)
    hub=app.extensions['hub'];hub.enabled=True
    hub.current=Mock(return_value={'id':1,'role':'admin','hub_role':'admin'})
    hub.call=Mock(side_effect=HubError('Rejected by Hub',401))
    with client.session_transaction() as session:session['hub_uid']=1
    response=client.get('/api/storage?proxmox=1')
    assert response.status_code==503
    assert response.json['error_code']=='storage_integration_unavailable'
    assert client.get('/api/storage').status_code==200
    with client.session_transaction() as session:assert session['authenticated']
    hub.call=Mock(return_value={'ok':True,'storages':[]})
    assert client.get('/api/storage?proxmox=1').json['storages']==[]
    hub.current.side_effect=HubError('Access removed',401)
    assert client.get('/api/storage?proxmox=1').status_code==401
    with client.session_transaction() as session:assert not session.get('authenticated')


def test_storage_usage_reads_selected_host_mount_and_requires_admin(tmp_path,monkeypatch):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    app.extensions['runtime'].host_downloads='/downloads'
    helper=Mock(return_value={'total_bytes':1000,'used_bytes':750,'free_bytes':250})
    monkeypatch.setattr(Storage,'helper',helper)
    assert app.test_client().get('/api/storage/usage').status_code==401
    client,_=login(app)
    result=client.get('/api/storage/usage')
    assert result.status_code==200
    assert result.json=={'ok':True,'path':'/downloads','total_bytes':1000,'used_bytes':750,'free_bytes':250}
    helper.assert_called_once_with('usage',source='/downloads')
    storage=Storage(app.extensions['runtime'])
    app.extensions['runtime'].stop=Mock()
    helper.return_value['ready']=True
    storage.select('/mnt/media')
    del helper.return_value['ready']
    helper.reset_mock()
    assert client.get('/api/storage/usage').json['path']=='/mnt/media'
    helper.assert_called_once_with('usage',source='/mnt/media')
    hub=app.extensions['hub'];hub.enabled=True
    hub.current=Mock(return_value={'id':1,'hub_role':'user'})
    assert client.get('/api/storage/usage').status_code==403
    hub.enabled=False
    helper.side_effect=OSError('unavailable')
    assert client.get('/api/storage/usage').status_code==503


def test_usage_helper_only_mounts_selected_folder_read_only(tmp_path):
    runtime=Mock(state=State(tmp_path),image='seed',uid=1000,gid=1000)
    worker=runtime.client.containers.create.return_value
    worker.wait.return_value={'StatusCode':0}
    worker.logs.return_value=b'{"total_bytes":1000,"used_bytes":750,"free_bytes":250}'
    assert Storage(runtime).helper('usage',source='/mnt/media')['free_bytes']==250
    mount=runtime.client.containers.create.call_args.kwargs['mounts'][0]
    assert mount['Source']=='/mnt/media' and mount['Target']=='/folder' and mount['ReadOnly'] is True
    worker.remove.assert_called_once_with(force=True)


def test_usage_measures_filesystem_without_scanning_directories(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import storage_browser
    disk=Mock(return_value=SimpleNamespace(total=1000,used=750,free=250))
    monkeypatch.setattr(storage_browser.shutil,'disk_usage',disk)
    assert storage_browser.usage(tmp_path)=={'total_bytes':1000,'used_bytes':750,'free_bytes':250}
    disk.assert_called_once_with(tmp_path)
