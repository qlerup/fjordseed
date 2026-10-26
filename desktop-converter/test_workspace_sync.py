import json
from unittest.mock import Mock

import pytest

import workspace_sync as sync


def test_sync_uses_encrypted_token_and_reports_current_selection_only(tmp_path,monkeypatch):
    import windows_secret
    connection=tmp_path/'connection.json';preferences=tmp_path/'preferences.json'
    connection.write_text(json.dumps({'server':'http://seed.test','token_dpapi':'encrypted'}))
    preferences.write_text(json.dumps({'media_folder':r'M:\Bibliotek'}))
    monkeypatch.setattr(windows_secret,'unprotect',lambda value:'fsw_test' if value=='encrypted' else '')
    monkeypatch.setattr(sync,'inventory',Mock(return_value=([{'name':'Show/S01/E01.mkv','size':12}],False)))
    response=Mock()
    response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    response.read.return_value=json.dumps({'ok':True,'media_folder':r'M:\Bibliotek'}).encode()
    opener=Mock();opener.open.return_value=response
    monkeypatch.setattr(sync.urllib.request,'build_opener',Mock(return_value=opener))
    assert sync.sync_folder(connection,preferences)==r'M:\Bibliotek'
    request=opener.open.call_args.args[0]
    assert request.full_url=='http://seed.test/api/conversion/worker/workspace'
    assert request.get_header('Authorization')=='Bearer fsw_test'
    assert json.loads(request.data)=={'version':1,'media_folder':r'M:\Bibliotek','files':[{'name':'Show/S01/E01.mkv','size':12}],'truncated':False}
    assert 'fsw_test' not in connection.read_text()
    response.read.return_value=b'{"ok":true,"media_folder":"different"}'
    with pytest.raises(sync.WorkerError):sync.sync_folder(connection,preferences)


def test_inventory_groups_by_relative_path_and_skips_private_and_original_folders(tmp_path):
    for name in ('Show/S01/E01.mkv','Show/S01/E02.mp4','film.mkv','Seeder/original.mkv','.incomplete/partial.mkv','notes.txt'):
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'video')
    files,truncated=sync.inventory(str(tmp_path))
    assert {f['name'] for f in files}=={'Show/S01/E01.mkv','Show/S01/E02.mp4','film.mkv'}
    assert all(f['size']==5 for f in files)
    assert not truncated
    assert sync.inventory('')==([],False)
    with pytest.raises(ValueError):sync.inventory(str(tmp_path/'missing'))


def test_select_file_uses_existing_shared_path_without_reading_or_copying_video(tmp_path,monkeypatch):
    from pathlib import Path
    video=tmp_path/'Series'/'E01.mkv';video.parent.mkdir();video.write_bytes(b'video')
    command={'id':'a'*32,'media_folder':str(tmp_path),'name':'Series/E01.mkv','size':5,'state':'queued'}
    monkeypatch.setattr(Path,'open',Mock(side_effect=AssertionError('Must not read the video')))
    assert sync.selected_file(command,str(tmp_path))==video
    for fields in ({'name':'../outside.mkv'},{'name':'/absolute.mkv'},{'name':'Series\\E01.mkv'},
                   {'size':6},{'name':'missing.mkv'},{'media_folder':'different'}):
        with pytest.raises((ValueError,OSError)):sync.selected_file({**command,**fields},str(tmp_path))


def test_receive_acknowledges_once_and_reselects_after_app_restart(tmp_path):
    import queue,threading
    video=tmp_path/'film.mkv';video.write_bytes(b'video')
    prefs=tmp_path/'preferences.json';prefs.write_text(json.dumps({'media_folder':str(tmp_path)}))
    def worker():
        item=sync.WorkspaceSync.__new__(sync.WorkspaceSync)
        item.preferences_path=prefs;item.selection_id=None;item.receipt=None
        item.messages=queue.SimpleQueue();item.changed=threading.Event()
        return item
    command={'id':'a'*32,'media_folder':str(tmp_path),'name':'film.mkv','size':5,'state':'queued'}
    item=worker();item.receive(command,str(tmp_path))
    state,value=item.messages.get_nowait()
    assert state=='selected' and value['path']==str(video)
    assert item.receipt=={'id':'a'*32,'state':'selected'} and item.changed.is_set()
    item.receive(command,str(tmp_path));assert item.messages.empty()
    restarted=worker();restarted.receive({**command,'state':'selected'},str(tmp_path))
    assert restarted.messages.get_nowait()[0]=='selected'
    item.receive({**command,'id':'b'*32,'size':6},str(tmp_path))
    assert item.receipt['state']=='error'
    prefs.write_text(json.dumps({'media_folder':'changed'}))
    item.receive(command,str(tmp_path))
    assert item.selection_id=='b'*32
