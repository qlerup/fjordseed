import json

from converter_worker import report


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
