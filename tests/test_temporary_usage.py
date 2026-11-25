import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from storage import Storage
from state import State
from storage_browser import temporary_usage
from test_app import create_app, FakeRuntime, login


@pytest.mark.skipif(not hasattr(os,'fwalk') or os.name=='nt',reason='Linux allocated-block accounting')
def test_allocated_bytes_rss_subset_links_sparse_and_old_locations(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b'
    rss=a/'.incomplete'/'rss';manual=a/'.incomplete'/'manual'
    rss.mkdir(parents=True);manual.mkdir()
    (b/'.incomplete'/'old').mkdir(parents=True)
    (a/'.fjordseed-buffer').mkdir()
    (a/'.fjordseed-buffer'/'legacy').write_bytes(b'l'*5000)
    (rss/'episode').write_bytes(b'x'*5000)
    os.link(rss/'episode',manual/'duplicate')
    (manual/'other').write_bytes(b'y'*5000)
    (b/'.incomplete'/'old'/'episode').write_bytes(b'z'*5000)
    with (manual/'sparse').open('wb') as f:f.truncate(1024**3)
    (a/'retained').write_bytes(b'p'*10000)
    (rss/'link').symlink_to(a/'retained')
    (rss/'directory-link').symlink_to(b,target_is_directory=True)
    allocated=lambda p:p.stat().st_blocks*512
    expected_rss=allocated(rss/'episode')+allocated(b/'.incomplete'/'old'/'episode')
    result=temporary_usage([a,b],{'rss_stages':[['.incomplete/rss'],['.incomplete/old']],'selected':0})
    assert result['rss_temporary_bytes']==expected_rss
    assert result['current_rss_bytes']==expected_rss
    assert len(result['download_stage_usage'])==2
    current=next(r for r in result['download_stage_usage'] if r['stage']=='.incomplete/rss')
    assert current['bytes']==allocated(rss/'episode')
    assert current['reclaimable_bytes']==0  # Another hardlink keeps the disk blocks alive.
    assert result['temporary_bytes']==expected_rss+allocated(manual/'other')+allocated(manual/'sparse')+allocated(a/'.fjordseed-buffer/legacy')
    assert result['current_temporary_bytes']==result['temporary_bytes']
    unknown_rss=temporary_usage([a,b],{'selected':0,'rss_known':False})
    assert unknown_rss['current_rss_bytes'] is None
    assert unknown_rss['current_temporary_bytes']==result['temporary_bytes']
    (rss/'episode').unlink()
    (manual/'duplicate').unlink()
    assert temporary_usage([a,b])['temporary_bytes']==result['temporary_bytes']-allocated(b/'.incomplete/old/episode')


def test_stage_mapping_uses_rss_history_and_all_storage_locations(tmp_path):
    state=State(tmp_path)
    root=tmp_path/'qbit';root.mkdir(exist_ok=True)
    (root/'download-storage.json').write_text(json.dumps({
        'rss':{'stage':'/download-locations/a/.incomplete/episode'},
        'manual':{'stage':'/downloads/.incomplete/manual'}}))
    (root/'green-credit.json').write_text(json.dumps({'rss':{'rss_feed_id':'feed'}}))
    storage=Storage(Mock(state=state,host_downloads='/mnt/original'))
    storage.settings=Mock(return_value={'selected':'a','locations':[{'id':'a','path':'/mnt/media'}]})
    storage.helper=Mock(return_value={'temporary_bytes':50})
    paths=('/mnt/original','/mnt/media')
    assert storage.temporary_usage(paths)['temporary_bytes']==50
    args=storage.helper.call_args
    config=json.loads(args.args[1])
    assert config['rss_stages']==[[],['.incomplete/episode']]
    assert config['download_stages']==[['.incomplete/manual'],['.incomplete/episode']]
    assert config['selected']==1


def test_endpoint_requires_login_and_caches_scans(tmp_path,monkeypatch):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    runtime=app.extensions['runtime']
    runtime.host_downloads='/mnt/media'
    runtime.rpc=Mock(return_value={'torrents':[{'hash':'manual','progress':1,'state':'stalledUP',
        'share_limit_action':'RemoveWithContent','seeding_time':3600,'seeding_time_limit':3000}]})
    assert app.test_client().get('/api/storage/temporary-usage').status_code==401
    measure=Mock(return_value={'temporary_bytes':123,'current_temporary_bytes':0,'rss_temporary_bytes':None,'current_rss_bytes':None,
        '_release_sources':[{'hashes':['manual'],'bytes':123,'reclaimable_bytes':123}]})
    monkeypatch.setattr(Storage,'temporary_usage',measure)
    client,_=login(app)
    for _ in range(2):
        response=client.get('/api/storage/temporary-usage')
        assert response.status_code==200 and response.json['temporary_bytes']==123
        assert response.json['current_temporary_bytes']==0
        assert response.json['release_schedule']['count']==1
        assert response.json['release_schedule']['scheduled_bytes']==123
    assert measure.call_count==1
