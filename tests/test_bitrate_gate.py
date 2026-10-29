import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import conversion
import download_storage as storage
from test_conversion import job, record

decisions = conversion.bitrate_decisions


@pytest.mark.parametrize('total,convert',[(30_000_000,False),(31_500_000,False),(31_500_001,True)])
def test_total_bitrate_strictly_above_five_percent(monkeypatch,tmp_path,total,convert):
    monkeypatch.setattr('media_bitrates.probe',Mock(return_value={'video_bps':20_000_000,'total_bps':total}))
    result=decisions([{'name':'movie.mp4','size':1}],tmp_path,30)
    assert result[0]['convert'] is convert


def test_unknown_total_is_not_silently_kept(monkeypatch,tmp_path):
    monkeypatch.setattr('media_bitrates.probe',Mock(return_value={'video_bps':20_000_000,'total_bps':None}))
    with pytest.raises(ValueError,match='bitrate'):decisions([{'name':'movie.mkv','size':1}],tmp_path,30)


def test_below_threshold_publishes_original_without_gpu_or_new_request(job,monkeypatch):
    root,stage,api,row=job
    monkeypatch.setattr(conversion,'bitrate_decisions',decisions)
    monkeypatch.setattr('media_bitrates.probe',Mock(return_value={'total_bps':21_000_000}))
    # The configured target in this fixture is 20 Mbps, hence limit 21 Mbps.
    assert storage.publish_complete(api,[row])==[]
    saved=record()
    assert saved['published'] and saved['bitrate_skipped']
    assert (root/'Movie'/'film.mkv').read_bytes()==b'original'
    assert (stage/'film.mkv').read_bytes()==b'original'
    assert not (stage/conversion.DIRECTORY/'request.json').exists()


def test_above_threshold_preserves_conversion_intent(job,monkeypatch):
    root,stage,api,row=job
    monkeypatch.setattr(conversion,'bitrate_decisions',decisions)
    monkeypatch.setattr('media_bitrates.probe',Mock(return_value={'total_bps':21_000_001}))
    assert storage.publish_complete(api,[row])==[]
    request=json.loads((stage/conversion.DIRECTORY/'request.json').read_text())
    assert request['files'][0]['convert'] is True
    assert not record().get('published')


def test_mixed_pack_marks_each_file_independently(monkeypatch,tmp_path):
    monkeypatch.setattr('media_bitrates.probe',lambda path:{'total_bps':40_000_000 if path.name=='high.mkv' else 20_000_000})
    result=decisions([{'name':'low.mp4','size':1},{'name':'high.mkv','size':1},{'name':'sub.srt','size':1}],tmp_path,30)
    assert result[0]['convert'] is False and result[1]['convert'] is True
    assert 'convert' not in result[2]


def test_automatic_scan_records_dolby_for_each_file(monkeypatch,tmp_path):
    monkeypatch.setattr('media_bitrates.probe',lambda path:{'total_bps':40_000_000,'dolby_vision':path.name=='dv.mkv','dolby_vision_profile':'7' if path.name=='dv.mkv' else None,'dolby_vision_supported':True if path.name=='dv.mkv' else None})
    result=decisions([{'name':'dv.mkv','size':1},{'name':'hdr.mkv','size':1}],tmp_path,30)
    assert result[0]['dolby_vision'] is True and result[0]['dolby_vision_profile']=='7'
    assert result[1]['dolby_vision'] is False and all(f['convert'] for f in result)
