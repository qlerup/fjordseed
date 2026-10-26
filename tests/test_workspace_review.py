from pathlib import PureWindowsPath

import pytest

from remote_conversion import RemoteConversion,skipped,series
from test_remote_conversion import setup


def workspace(setup):
    app,manager,client,h=setup
    pc=manager.create('PC');folder=r'M:\Bibliotek'
    files=[{'name':'Show.S01/Show.S01E01.mkv','size':1},
           {'name':'Show.S02/Show.S02E01.mkv','size':2},
           {'name':'Other/film.mkv','size':3}]
    manager.workspace(pc,folder,files)
    return app,manager,client,h,pc,folder,files


def test_skip_file_folder_series_and_restore_are_durable_and_do_not_touch_media(setup):
    app,manager,client,h,pc,folder,files=workspace(setup)
    def update(path,kind,value):return manager.skip(pc['id'],folder,path,kind,value)['skip_rules']
    rules=update('Show.S01','folder',True)
    assert skipped(files[0]['name'],rules) and not skipped(files[1]['name'],rules)
    rules=update('show','series',True)
    assert skipped(files[0]['name'],rules) and skipped(files[1]['name'],rules)
    assert not skipped(files[2]['name'],rules)
    rules=update(files[0]['name'],'file',False)
    assert not skipped(files[0]['name'],rules) and skipped(files[1]['name'],rules)
    rules=update('','folder',True)
    assert all(skipped(f['name'],rules) for f in files)
    rules=update('show','series',False)
    assert not skipped(files[0]['name'],rules) and not skipped(files[1]['name'],rules)
    assert skipped(files[2]['name'],rules)
    manager.workspace(pc,folder,files)  # PC heartbeats cannot overwrite review choices.
    restored=RemoteConversion(manager.state,manager.runtime)
    assert restored.public()[0]['skip_rules']==rules
    assert restored.public()[0]['files'][0]['series_key']=='show'
    app.extensions['runtime'].rpc.assert_not_called()
    manager.rpc.assert_not_called()
    with pytest.raises(ValueError,match='sprunget'):
        manager.select_file(pc['id'],folder,files[2]['name'])
    assert update('','folder',False)==[]


def test_review_routes_require_session_csrf_and_current_folder(setup):
    app,manager,client,h,pc,folder,files=workspace(setup)
    url='/api/conversion/devices/'+pc['id']+'/skip'
    data={'media_folder':folder,'path':files[0]['name'],'kind':'file','skip':True}
    assert app.test_client().post(url,json=data).status_code==403
    assert client.post(url,json=data).status_code==403
    assert client.post(url,headers=h,json=data).status_code==200
    for changes in ({'path':'../outside'},{'path':'/absolute'},{'kind':'unknown'},{'skip':'yes'},
                    {'media_folder':r'N:\Other'},{'path':'absent.mkv'}):
        assert client.post(url,headers=h,json={**data,**changes}).status_code==400
    assert client.get('/api/conversion').json['devices'][0]['skip_rules']
    manager.workspace(pc,r'N:\Other',[])
    assert manager.public()[0]['skip_rules']==[]
    manager.workspace(pc,folder,files)
    assert manager.public()[0]['skip_rules']


def test_series_detection_handles_separate_seasons_and_nested_season_folders():
    assert series('Divaer.I.Junglen.S01.DANISH/foo.mkv')['series_key']=='divaer i junglen'
    assert series('Divaer.I.Junglen.S02.DANISH/foo.mkv')['series_key']=='divaer i junglen'
    assert series('Show/Season 2/episode.mkv')['series_key']=='show'
    assert series('Movie.2026.2160p.mkv')=={}


def test_bitrate_request_uses_only_stored_pc_inventory_and_empty_folder_skips_probe(setup):
    app,manager,client,h,pc,folder,files=workspace(setup)
    runtime=app.extensions['runtime']
    runtime.rpc.return_value={'files':[{'name':files[0]['name'],'size':1,'video_bps':65000000,'total_bps':68000000,'state':'ready'}],'pending':False}
    url='/api/conversion/devices/'+pc['id']+'/bitrates'
    assert app.test_client().get(url).status_code==401
    result=client.get(url)
    assert result.status_code==200 and result.json['files'][0]['video_bps']==65000000
    runtime.rpc.assert_called_once_with('library-bitrates',{'files':files})
    runtime.rpc.reset_mock()
    manager.workspace(pc,'',[])
    assert client.get(url).json['files']==[]
    runtime.rpc.assert_not_called()
