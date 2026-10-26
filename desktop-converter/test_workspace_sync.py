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
