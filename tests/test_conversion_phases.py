import json

from converter_worker import report
from converter_worker import audio_progress


def test_worker_changes_phase_without_carrying_old_encoding_percentage(tmp_path):
    report(tmp_path,'a'*32,'encoding','GPU',77)
    first=json.loads((tmp_path/'status.json').read_text())
    report(tmp_path,'a'*32,'encoding','GPU',99)
    current=json.loads((tmp_path/'status.json').read_text())
    assert current['stage_started_at']==first['stage_started_at']
    assert current['phase_progress']==99
    report(tmp_path,'a'*32,'metadata','Bevarer HDR')
    current=json.loads((tmp_path/'status.json').read_text())
    assert current['stage']=='metadata' and current['phase_progress'] is None
    assert current['stage_started_at']>=first['stage_started_at']
    report(tmp_path,'a'*32,'verifying','Kontrollerer resultatet')
    current=json.loads((tmp_path/'status.json').read_text())
    assert current['stage']=='verifying' and current['phase_progress'] is None


def test_audio_progress_and_eta_use_processed_media_time():
    assert audio_progress('out_time_us=25000000',100,10)==(25,30)
    assert audio_progress('out_time_us=25000000',100,2)==(25,None)
    assert audio_progress('out_time_us=100000000',100,10)==(99.9,0)
    for line,duration in [('out_time_us=N/A',100),('speed=4x',100),('out_time_us=-1',100),('out_time_us=1',0),('out_time_us=nan',100)]:
        assert audio_progress(line,duration,10) is None


def test_audio_stage_resets_gpu_timing_and_clears_eta_afterwards(tmp_path):
    report(tmp_path,'a'*32,'encoding','GPU',99)
    report(tmp_path,'a'*32,'encoding','Audio',25,stage='audio_encoding',eta_seconds=30)
    data=json.loads((tmp_path/'status.json').read_text())
    assert data['stage']=='audio_encoding' and data['phase_progress']==25 and data['eta_seconds']==30
    report(tmp_path,'a'*32,'verifying','Checking')
    data=json.loads((tmp_path/'status.json').read_text())
    assert data['eta_seconds'] is None and data['phase_progress'] is None
