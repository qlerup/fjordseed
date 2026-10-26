import hashlib
import json
from pathlib import PurePosixPath
from unittest.mock import Mock

import pytest

from app import create_app
from test_app import FakeRuntime,login


@pytest.fixture
def setup(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    app.extensions['runtime'].host_downloads=PurePosixPath('/downloads')
    manager=app.extensions['remote_conversion']
    manager.rpc=Mock(return_value=None)
    client,headers=login(app)
    return app,manager,client,headers


def test_tokens_are_scoped_hashed_revocable_and_never_listed(setup):
    app,manager,client,h=setup
    assert app.test_client().post('/api/conversion/devices',json={'name':'PC'}).status_code==403
    assert client.post('/api/conversion/devices',json={'name':'PC'}).status_code==403
    created=client.post('/api/conversion/devices',json={'name':'PC'},headers=h)
    assert created.status_code==201
    token=created.json['token'];ident=created.json['id']
    raw=manager.path.read_text()
    assert token not in raw and hashlib.sha256(token.encode()).hexdigest() in raw
    assert token not in client.get('/api/conversion').get_data(as_text=True)
    worker=app.test_client();auth={'Authorization':'Bearer '+token}
    assert worker.post('/api/conversion/worker/claim',headers=auth,json={}).status_code==200
    assert worker.get('/api/status',headers=auth).status_code==401
    assert worker.post('/api/conversion/worker/claim').status_code==401
    assert client.post('/api/conversion/worker/claim',json={}).status_code==401
    assert client.post('/api/conversion/devices/'+ident+'/revoke',headers=h).status_code==200
    assert worker.post('/api/conversion/worker/claim',headers=auth,json={}).status_code==401


def test_remote_device_heartbeat_and_bounded_upload(setup):
    app,manager,client,h=setup
    token=client.post('/api/conversion/devices',json={'name':'PC'},headers=h).json['token']
    auth={'Authorization':'Bearer '+token};worker=app.test_client()
    assert worker.post('/api/conversion/worker/heartbeat',headers=auth,json={'version':1,'gpu_ready':False}).status_code==409
    assert worker.post('/api/conversion/worker/heartbeat',headers=auth,json={'version':1,'gpu_ready':True}).status_code==200
    assert manager.public()[0]['online']
    assert manager.rpc.call_args.args[0]=='heartbeat'
    manager.upload=Mock(return_value={'offset':4})
    result=worker.put('/api/conversion/worker/jobs/'+'a'*32+'/files/0?offset=0',headers={**auth,'X-Job-Lease':'b'*32},data=b'file')
    assert result.status_code==200 and manager.upload.call_args.args[2]==b'file'
    assert worker.put('/api/conversion/worker/jobs/'+'a'*32+'/files/0?offset=-1',headers=auth,data=b'x').status_code==409
    assert worker.put('/api/conversion/worker/jobs/'+'a'*32+'/files/0?offset=0',headers=auth,data=b'x'*(32*1024*1024+1)).status_code==413


def test_conversion_settings_separate_from_streaming_and_default_off(setup):
    app,manager,client,h=setup
    assert client.get('/api/conversion').json['conversion_enabled'] is False
    result=client.post('/api/conversion',headers=h,json={'conversion_enabled':False,'conversion_bitrate':20,'conversion_target':'pc'})
    assert result.status_code==200 and result.json['conversion_target']=='pc'
    assert result.json['enabled'] is True and result.json['conversion_enabled'] is False
    assert app.extensions['state'].get()['streaming']['conversion_target']=='pc'
    for body in ([],{'conversion_target':'anywhere'},{'conversion_target':'pc','conversion_enabled':'yes'}):
        assert client.post('/api/conversion',headers=h,json=body).status_code==400


def test_workspace_is_durable_scoped_to_token_and_does_not_claim_jobs(setup):
    app,manager,client,h=setup
    first=manager.create('First');second=manager.create('Second')
    worker=app.test_client();url='/api/conversion/worker/workspace'
    data={'version':1,'media_folder':r'M:\Bibliotek','id':second['id']}
    assert worker.post(url,json=data).status_code==401
    auth={'Authorization':'Bearer '+first['token']}
    result=worker.post(url,json=data,headers=auth)
    assert result.status_code==200 and result.json['media_folder']==r'M:\Bibliotek'
    persisted=json.loads(manager.path.read_text())
    assert persisted[0]['media_folder']==r'M:\Bibliotek'
    assert 'media_folder' not in persisted[1]
    assert manager.public()[0]['online'] and not manager.public()[0]['gpu_ready']
    assert client.get('/api/conversion').json['devices'][0]['media_folder']==r'M:\Bibliotek'
    manager.rpc.assert_not_called()
    for folder in (None,[],r'M:relative','/server/path',r'M:\..\outside','x'*2049,'M:\\bad\npath'):
        assert worker.post(url,headers=auth,json={'version':1,'media_folder':folder}).status_code==409
    unc=r'\\server\Medier\Bibliotek'
    assert worker.post(url,headers=auth,json={'version':1,'media_folder':unc}).json['media_folder']==unc
    manager.revoke(first['id'])
    assert worker.post(url,headers=auth,json=data).status_code==401


def test_workspace_files_follow_folder_selection_and_empty_selection_clears_list(setup):
    app,manager,client,h=setup
    device=manager.create('PC');auth={'Authorization':'Bearer '+device['token']}
    worker=app.test_client();url='/api/conversion/worker/workspace'
    files=[{'name':'Show/S01/E01.mkv','size':123}]
    data={'version':1,'media_folder':r'M:\Bibliotek','files':files,'truncated':False}
    assert worker.post(url,headers=auth,json=data).status_code==200
    assert manager.public()[0]['files']==files
    assert manager.public()[0]['files_updated_at']>0
    for bad in ([{'name':'../outside.mkv','size':1}],[{'name':'/absolute.mkv','size':1}],[{'name':'film.mkv','size':-1}],files*2):
        assert worker.post(url,headers=auth,json={**data,'files':bad}).status_code==409
    assert manager.public()[0]['files']==files
    assert worker.post(url,headers=auth,json={**data,'media_folder':'','files':[]}).status_code==200
    assert manager.public()[0]['files']==[] and manager.public()[0]['media_folder']==''
    manager.rpc.assert_not_called()


def test_shared_file_selection_is_scoped_durable_and_acknowledged_without_transfer(setup):
    app,manager,client,h=setup
    pc=manager.create('PC');other=manager.create('Other')
    worker=app.test_client();auth={'Authorization':'Bearer '+pc['token']}
    folder=r'M:\Bibliotek';files=[{'name':'Series/E01.mkv','size':123}]
    sync={'version':1,'media_folder':folder,'files':files}
    url='/api/conversion/devices/'+pc['id']+'/select'
    worker.post('/api/conversion/worker/workspace',headers=auth,json=sync)
    data={'media_folder':folder,'name':files[0]['name']}
    assert worker.post(url,json=data).status_code==403
    assert client.post(url,json=data).status_code==403
    assert worker.post(url,headers=auth,json=data).status_code==403
    queued=client.post(url,headers=h,json=data)
    assert queued.status_code==202
    selection=queued.json['selection']
    assert selection['state']=='queued'
    assert manager.public()[0]['selection']==selection
    response=worker.post('/api/conversion/worker/workspace',headers=auth,json=sync)
    assert response.json['selection']==selection
    second=worker.post('/api/conversion/worker/workspace',headers={'Authorization':'Bearer '+other['token']},json={'version':1,'media_folder':''})
    assert second.json['selection'] is None
    ack={**sync,'selection_result':{'id':selection['id'],'state':'selected'}}
    assert worker.post('/api/conversion/worker/workspace',headers=auth,json=ack).json['selection']['state']=='selected'
    newer=client.post(url,headers=h,json=data).json['selection']
    response=worker.post('/api/conversion/worker/workspace',headers=auth,json=ack)
    assert response.json['selection']['id']==newer['id'] and response.json['selection']['state']=='queued'
    for bad in ({**data,'media_folder':r'N:\Other'},{**data,'name':'../outside.mkv'}):
        assert client.post(url,headers=h,json=bad).status_code==400
    changed=worker.post('/api/conversion/worker/workspace',headers=auth,json={**sync,'media_folder':r'N:\Other'})
    assert changed.json['selection']['state']=='cancelled'
    manager.rpc.assert_not_called()


def test_missing_shared_file_cannot_be_acknowledged_as_selected(setup):
    app,manager,client,h=setup
    pc=manager.create('PC');auth={'Authorization':'Bearer '+pc['token']}
    worker=app.test_client();folder=r'M:\Bibliotek'
    manager.workspace(pc,folder,[{'name':'film.mkv','size':1}])
    selection=manager.select_file(pc['id'],folder,'film.mkv')
    result=worker.post('/api/conversion/worker/workspace',headers=auth,json={
        'version':1,'media_folder':folder,'files':[],
        'selection_result':{'id':selection['id'],'state':'selected'}})
    assert result.json['selection']['state']=='error'
    assert manager.devices()[0]['selection']['state']=='error'
    manager.rpc.assert_not_called()


def test_conversion_controls_live_in_their_own_settings_tab(setup):
    app,manager,client,h=setup
    html=client.get('/').get_data(as_text=True)
    assert 'href="#conversion"' in html and 'id="conversion-view"' in html
    stream=html.split('id="streaming-view"',1)[1].split('id="conversion-view"',1)[0]
    assert 'id="conversion-enabled"' not in stream
    assert html.count('id="conversion-enabled"')==1


@pytest.mark.parametrize('rate',[20,30,40])
def test_quality_choices_are_saved_and_returned_for_pc_jobs(setup,rate):
    app,manager,client,h=setup
    assert client.get('/api/conversion').json['conversion_bitrate']==30
    result=client.post('/api/conversion',headers=h,json={
        'conversion_enabled':False,'conversion_bitrate':rate,'conversion_target':'pc'})
    assert result.status_code==200
    assert result.json['conversion_bitrate']==rate
    assert client.get('/api/conversion').json['conversion_bitrate']==rate
    assert app.extensions['runtime'].state.get()['streaming']['conversion_bitrate']==rate


@pytest.mark.parametrize('rate',[0,21,50,True,'40'])
def test_invalid_quality_choices_are_rejected(setup,rate):
    app,manager,client,h=setup
    result=client.post('/api/conversion',headers=h,json={
        'conversion_enabled':False,'conversion_bitrate':rate,'conversion_target':'pc'})
    assert result.status_code==400
    assert client.get('/api/conversion').json['conversion_bitrate']==30


def test_library_conversion_endpoints_are_session_and_csrf_protected(setup):
    app,manager,client,h=setup
    assert app.test_client().get('/api/conversion/library').status_code==401
    assert client.post('/api/conversion/library',json={'id':'a'*64,'bitrate':40}).status_code==403
    runtime=app.extensions['runtime']
    runtime.rpc.return_value={'items':[],'jobs':[],'truncated':False}
    assert client.get('/api/conversion/library').json['items']==[]
    runtime.rpc.assert_called_with('library-list',{})
    assert client.post('/api/conversion/library',headers=h,json={'id':'a'*64,'bitrate':40}).status_code==202
    runtime.rpc.assert_called_with('library-convert',{'id':'a'*64,'bitrate':40})
    assert client.post('/api/conversion/library/'+'b'*32+'/retry',headers=h).status_code==200
    runtime.rpc.assert_called_with('library-retry',{'id':'b'*32})
    assert client.post('/api/conversion/library/'+'b'*32+'/cancel',headers=h).status_code==200
    runtime.rpc.assert_called_with('library-cancel',{'id':'b'*32})
    assert client.post('/api/conversion/library',headers=h,json=[]).status_code==400


def test_download_chunk_negotiation_preserves_old_client_size_and_checks_bound(setup):
    import hashlib
    app,manager,client,h=setup
    token=client.post('/api/conversion/devices',json={'name':'PC'},headers=h).json['token']
    auth={'Authorization':'Bearer '+token,'X-Job-Lease':'b'*32}
    manager.rpc=Mock(return_value=b'data')
    worker=app.test_client();url='/api/conversion/worker/jobs/'+'a'*32+'/files/0?offset=0'
    for query,expected in [('',8*1024**2),('&size='+str(32*1024**2),32*1024**2)]:
        result=worker.get(url+query,headers=auth)
        assert result.status_code==200 and result.data==b'data'
        assert result.headers['X-Chunk-SHA256']==hashlib.sha256(b'data').hexdigest()
        assert manager.rpc.call_args.args[2]['size']==expected
    for size in ['0','-1','many',str(32*1024**2+1)]:
        assert worker.get(url+'&size='+size,headers=auth).status_code==409
