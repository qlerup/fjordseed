import json
import subprocess
from unittest.mock import Mock

import media_bitrates as metadata


def test_header_probe_uses_video_bps_and_keeps_total_bitrate_separate(tmp_path,monkeypatch):
    path=tmp_path/'film.mkv';path.write_bytes(b'video')
    run=Mock(return_value=Mock(stdout=json.dumps({'streams':[{'tags':{'BPS':'65000000'}}],
        'format':{'bit_rate':'68000000','duration':'100'}})))
    monkeypatch.setattr(metadata.subprocess,'run',run)
    assert metadata.probe(path)=={'state':'ready','video_bps':65000000,'total_bps':68000000}
    assert run.call_args.kwargs['timeout']==2
    run.return_value.stdout=json.dumps({'streams':[{}],'format':{'bit_rate':'12000000'}})
    assert metadata.probe(path)=={'state':'ready','video_bps':None,'total_bps':12000000}


def test_scan_is_bounded_cached_and_refreshes_when_file_changes(tmp_path,monkeypatch):
    root=tmp_path/'library';root.mkdir()
    monkeypatch.setattr(metadata.storage,'download_root',lambda:root)
    for index in range(3):(root/f'{index}.mkv').write_bytes(b'video')
    probe=Mock(return_value={'state':'ready','video_bps':30000000,'total_bps':33000000})
    monkeypatch.setattr(metadata,'probe',probe)
    files=[{'name':f'{i}.mkv','size':5} for i in range(3)]
    first=metadata.listing(files)
    assert first['pending'] and probe.call_count==2
    second=metadata.listing(files)
    assert not second['pending'] and probe.call_count==3
    metadata.listing(files);assert probe.call_count==3
    (root/'0.mkv').write_bytes(b'longer video')
    metadata.listing([{'name':'0.mkv','size':12}]);assert probe.call_count==4


def test_ambiguous_missing_and_failed_probes_do_not_invent_a_video_bitrate(tmp_path,monkeypatch):
    root=tmp_path/'library';root.mkdir()
    monkeypatch.setattr(metadata.storage,'download_root',lambda:root)
    for directory in ('A','B'):
        (root/directory).mkdir();(root/directory/'film.mkv').write_bytes(b'video')
    probe=Mock(side_effect=subprocess.TimeoutExpired('ffprobe',2))
    monkeypatch.setattr(metadata,'probe',probe)
    result=metadata.listing([{'name':'film.mkv','size':5},{'name':'missing.mkv','size':1}])
    assert all(f['state']=='unavailable' and f['video_bps'] is None for f in result['files'])
    probe.assert_not_called()
    result=metadata.listing([{'name':'A/film.mkv','size':5}])
    assert result['files'][0]['state']=='unavailable'
    metadata.listing([{'name':'A/film.mkv','size':5}]);assert probe.call_count==1
