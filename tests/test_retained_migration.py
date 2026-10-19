import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import download_storage as ds
from storage import Storage
from streaming import Streaming
from test_streaming import runtime
from test_app import create_app,FakeRuntime,login


def test_migration_is_only_published_for_enabled_connected_flix(tmp_path):
    r=runtime(tmp_path);streaming=Streaming(r)
    connection={'host_path':str(r.host_downloads),'library_path':'/library/Film'}
    streaming.save(True,connection,move_retained=True)
    settings=tmp_path/'rpc/download-settings.json'
    assert json.loads(settings.read_text())['retained_library_path']=='/downloads'
    assert streaming.public()['move_retained'] is True
    streaming.save(False)
    assert 'retained_library_path' not in json.loads(settings.read_text())
    streaming.save(True,{'host_path':'/mnt/other'})
    assert 'retained_library_path' not in json.loads(settings.read_text())
    before=r.state.path.read_text()
    with pytest.raises(ValueError):streaming.save(True,move_retained='true')
    assert r.state.path.read_text()==before


def test_api_saves_migration_preference_with_csrf_and_validates_type(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    app.extensions['runtime'].host_downloads='/downloads'
    client,headers=login(app)
    payload={'enabled':True,'move_retained':True}
    assert client.post('/api/streaming',json=payload).status_code==403
    result=client.post('/api/streaming',headers=headers,json=payload)
    assert result.status_code==200 and result.json['move_retained'] is True
    assert client.get('/api/streaming').json['move_retained'] is True
    assert client.post('/api/streaming',headers=headers,json={**payload,'move_retained':'true'}).status_code==400


@pytest.mark.parametrize('path,valid',[
    ('/downloads',True),('/downloads/old',True),('/download-locations/'+'a'*32+'/old',True),
    ('/downloads/../etc',False),('/etc',False),('/downloads-elsewhere',False),
    ('/download-locations/unknown',False),('/downloads/old\n',False),('/downloads\\old',False)])
def test_source_must_be_in_worker_download_mounts(path,valid):
    assert ds.managed_directory(path) is valid


@pytest.fixture
def migration(tmp_path,monkeypatch):
    library=tmp_path/'flix';library.mkdir()
    source=tmp_path/'old';source.mkdir()
    monkeypatch.setattr(ds,'retained_library',lambda:library.as_posix())
    # Production validates fixed container paths; tests use isolated temporary folders.
    monkeypatch.setattr(ds,'managed_directory',lambda value:Path(value).is_relative_to(tmp_path))
    row={'hash':'a'*40,'name':'My.Show.S01E01','progress':1,'state':'stalledUP',
         'share_limit_action':'Stop','save_path':source.as_posix()}
    return library,source,row


@pytest.mark.parametrize('published',[False,True])
def test_old_managed_and_legacy_torrents_move_without_changing_seed_policy(migration,published):
    library,source,row=migration
    if published:
        with ds.transaction() as entries:
            entries[row['hash']]={'stage':str(source/'old-stage'),'target':row['save_path'],'published':True}
    (source/'unrelated.txt').write_text('leave alone')
    api=Mock()
    assert ds.publish_complete(api,[row])==[]
    record=ds.read(ds.CONFIG/'download-storage.json',{})[row['hash']]
    assert Path(record['target'])==library/row['name']
    api.assert_called_once_with('torrents/setLocation',{'hashes':row['hash'],'location':str(Path(record['target']))})
    assert (source/'unrelated.txt').read_text()=='leave alone'
    api.reset_mock()
    assert ds.publish_complete(api,[{**row,'state':'moving','save_path':record['target']}])==[]
    assert not ds.read(ds.CONFIG/'download-storage.json',{})[row['hash']]['published']
    assert ds.publish_complete(api,[{**row,'save_path':record['target']}])==[]
    assert ds.read(ds.CONFIG/'download-storage.json',{})[row['hash']]['published']
    assert not (Path(record['target'])/ds.PUBLISHING_MARKER).exists()
    ds.publish_complete(api,[{**row,'save_path':record['target']}])
    api.assert_not_called()


@pytest.mark.parametrize('change',[{'progress':.99},{'state':'checkingUP'},
    {'share_limit_action':'RemoveWithContent'},{'state':'moving'}])
def test_incomplete_temporary_or_moving_torrents_are_not_adopted(migration,change):
    _,_,row=migration;api=Mock()
    assert ds.publish_complete(api,[{**row,**change}])==[]
    api.assert_not_called()
    assert not ds.read(ds.CONFIG/'download-storage.json',{})


def test_one_migration_at_a_time_and_collision_keeps_existing_files(migration):
    library,_,row=migration
    existing=library/row['name'];existing.mkdir();(existing/'keep.txt').write_text('keep')
    api=Mock();second={**row,'hash':'b'*40}
    ds.publish_complete(api,[row,second])
    assert api.call_count==1
    record=ds.read(ds.CONFIG/'download-storage.json',{})[row['hash']]
    assert Path(record['target']).name.startswith(row['name']+'-')
    api.reset_mock()
    ds.publish_complete(api,[{**row,'state':'moving'},second])
    api.assert_not_called()
    assert (existing/'keep.txt').read_text()=='keep'


def test_library_toggle_off_still_acknowledges_an_existing_move(migration,monkeypatch):
    _,_,row=migration;api=Mock()
    ds.publish_complete(api,[row])
    record=ds.read(ds.CONFIG/'download-storage.json',{})[row['hash']]
    monkeypatch.setattr(ds,'retained_library',lambda:None)
    api.reset_mock()
    ds.publish_complete(api,[{**row,'save_path':record['target']}])
    assert ds.read(ds.CONFIG/'download-storage.json',{})[row['hash']]['published']
    api.assert_not_called()


def test_deleted_payload_is_not_migrated_or_restarted(migration):
    _,source,row=migration
    with ds.transaction() as entries:
        entries[row['hash']]={'stage':row['save_path'],'target':row['save_path'],'published':True,'files_deleted':True}
    api=Mock();assert ds.publish_complete(api,[row])==[]
    api.assert_not_called()


def test_deleted_payload_does_not_block_other_migrations(migration):
    _,_,row=migration
    with ds.transaction() as entries:
        entries[row['hash']]={'stage':row['save_path'],'target':row['save_path'],
                             'published':False,'files_deleted':True,'migration':True}
    api=Mock()
    assert ds.publish_complete(api,[row,{**row,'hash':'b'*40}])==[]
    assert api.call_count==1
    assert api.call_args.args[1]['hashes']=='b'*40
