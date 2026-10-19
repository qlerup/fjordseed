import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import download_storage as ds
from state import State
from storage import Storage
from streaming import Streaming
from test_app import create_app,FakeRuntime,login


def runtime(tmp_path):
    return Mock(state=State(tmp_path),host_downloads=PurePosixPath('/mnt/downloads'))


def test_toggle_preserves_vpn_storage_and_existing_torrents_without_restart(tmp_path):
    r=runtime(tmp_path);r.state.save('a'*32,True)
    streaming=Streaming(r)
    assert streaming.public()['enabled'] is True
    result=streaming.save(False)
    assert result['enabled'] is False
    assert r.state.get()['profile_id']=='a'*32 and r.state.get()['enabled'] is True
    assert Storage(r).public()['buffer'] is None
    settings=json.loads((tmp_path/'rpc/download-settings.json').read_text())
    assert settings=={'path':'/downloads','streaming_enabled':False}
    r.stop.assert_not_called()
    assert Streaming(r).public()['enabled'] is False
    assert streaming.save(True)['enabled'] is True
    with pytest.raises(ValueError):streaming.save('false')


def test_direct_download_has_no_buffer_or_move_and_retains_per_torrent_choice(tmp_path,monkeypatch):
    settings=tmp_path/'download-settings.json'
    monkeypatch.setattr(ds,'SETTINGS',settings)
    settings.write_text(json.dumps({'streaming_enabled':True}))
    buffered=Path(ds.prepare(['a'*40]))
    settings.write_text(json.dumps({'streaming_enabled':False}))
    direct=Path(ds.prepare(['b'*40],'Serier'))
    assert ds.BUFFER not in direct.parts
    assert direct.parent==tmp_path/'downloads'/'Serier'
    assert (direct/ds.PUBLISHING_MARKER).is_file()
    assert ds.prepare(['a'*40])==str(buffered)
    settings.write_text(json.dumps({'streaming_enabled':True}))
    assert ds.prepare(['b'*40])==str(direct)
    api=Mock()
    row={'hash':'b'*40,'progress':.5,'state':'downloading','share_limit_action':'Stop','save_path':str(direct)}
    assert ds.publish_complete(api,[row])==[]
    assert (direct/ds.PUBLISHING_MARKER).exists()
    row.update(progress=1,state='stalledUP')
    assert ds.publish_complete(api,[row])==[]
    api.assert_not_called()
    assert not (direct/ds.PUBLISHING_MARKER).exists()
    assert ds.read(ds.CONFIG/'download-storage.json',{})['b'*40]['published'] is True


def test_direct_temporary_download_stays_hidden_until_automatic_removal(tmp_path,monkeypatch):
    settings=tmp_path/'download-settings.json';settings.write_text('{"streaming_enabled":false}')
    monkeypatch.setattr(ds,'SETTINGS',settings)
    path=Path(ds.prepare(['a'*40]));api=Mock()
    ds.publish_complete(api,[{'hash':'a'*40,'progress':1,'state':'stalledUP',
        'share_limit_action':'RemoveWithContent','save_path':str(path)}])
    assert (path/ds.PUBLISHING_MARKER).exists()
    api.assert_not_called()


def test_manual_torrent_add_uses_final_path_when_streaming_is_off(tmp_path,monkeypatch):
    from qbit_rpc import execute
    settings=tmp_path/'download-settings.json';settings.write_text('{"streaming_enabled":false}')
    monkeypatch.setattr(ds,'SETTINGS',settings)
    response=Mock(text='Ok.')
    response.json.return_value={'current_network_interface':'tun0','upnp':False}
    api=Mock(return_value=response)
    monkeypatch.setattr('qbit_rpc.call',api)
    execute('add',{'magnet':'magnet:?xt=urn:btih:'+'a'*40,'ratio_action':'keep','ratio_limit':1})
    options=next(call.args[1] for call in api.call_args_list if call.args[0]=='torrents/add')
    assert ds.BUFFER not in Path(options['savepath']).parts
    assert Path(options['savepath']).parent==tmp_path/'downloads'


def flix_mock(r):
    flix=Mock(status='running',labels={'com.docker.compose.service':'app'})
    flix.attrs={'Mounts':[{'Type':'bind','Source':'/mnt','Destination':'/library/server','RW':False},
                            {'Type':'bind','Source':'/opt/flix-data','Destination':'/data','RW':True}]}
    flix.exec_run.return_value=SimpleNamespace(exit_code=0,output=json.dumps({'ok':True,'sources':[
        {'id':'film','path':'/library/server/media/Film','available':True}]}).encode())
    r.client.containers.get.return_value=flix
    return flix


def test_discovery_translates_existing_read_only_flix_mounts(tmp_path):
    r=runtime(tmp_path);flix_mock(r)
    choices=Streaming(r).candidates()['choices']
    assert len(choices)==1 and choices[0]['path']=='/mnt/media/Film'
    assert choices[0]['library_path']=='/library/server/media/Film'
    assert not any(p['path'].startswith('/opt/flix-data') for p in choices)
    r.stop.assert_not_called()


def test_connect_validates_writable_and_mounts_existing_flix_source_in_seed(tmp_path,monkeypatch):
    r=runtime(tmp_path);flix=flix_mock(r)
    streaming=Streaming(r)
    choice=streaming.candidates()['choices'][0]
    helper=Mock(return_value={'ready':True});monkeypatch.setattr(Storage,'helper',helper)
    result=streaming.connect(choice['id'])
    assert result['enabled'] and result['connected']
    assert result['host_path']=='/mnt/media/Film'
    assert '/mnt/media/Film' in Storage(r).mounts()
    helper.assert_any_call('writable',source='/mnt/media/Film')
    assert all(len(call.args[0])==3 for call in flix.exec_run.call_args_list)
    r.stop.assert_called_once_with(remove=True)
    before=r.state.path.read_text()
    with pytest.raises(ValueError):streaming.connect('/etc')
    assert r.state.path.read_text()==before


def test_read_only_host_refusal_does_not_modify_settings_or_flix(tmp_path,monkeypatch):
    r=runtime(tmp_path);flix=flix_mock(r);streaming=Streaming(r)
    choice=streaming.candidates()['choices'][0]
    def helper(self,action,*args,**kwargs):
        if action=='writable':raise ValueError('read only')
        return {'ready':True}
    monkeypatch.setattr(Storage,'helper',helper)
    before=r.state.path.read_text()
    with pytest.raises(ValueError,match='read only'):streaming.connect(choice['id'])
    assert r.state.path.read_text()==before
    assert all('POST' not in call.args[0] for call in flix.exec_run.call_args_list)
    r.stop.assert_not_called()


def test_streaming_api_requires_auth_csrf_and_global_admin(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    app.extensions['runtime'].host_downloads=Path('/mnt/downloads')
    assert app.test_client().get('/api/streaming').status_code==401
    client,headers=login(app)
    assert client.post('/api/streaming',json={'enabled':False}).status_code==403
    assert client.post('/api/streaming',headers=headers,json={'enabled':False}).json['enabled'] is False
    assert client.post('/api/streaming',headers=headers,json={'enabled':'false'}).status_code==400
    assert client.get('/api/streaming').json['enabled'] is False
    hub=app.extensions['hub'];hub.enabled=True
    hub.current=Mock(return_value={'id':1,'role':'admin','hub_role':'user'})
    with client.session_transaction() as session:session['hub_uid']=1
    assert client.get('/api/streaming/flix').status_code==403
