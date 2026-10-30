from unittest.mock import Mock

import pytest

from storage_release import forecast, schedule


def torrent(**changes):
    return dict(hash='rss',name='A film',progress=1,state='stalledUP',share_limit_action='RemoveWithContent',
                seeding_time_limit=3000,seeding_time=48*3600,ratio_limit=1,seeding_goal_reached=False,
                required_seeding_seconds=50*3600,**changes)


def test_time_forecast_uses_remaining_seed_time_not_download_age():
    row=torrent();row['added_on']=1
    assert forecast(row,{},100)['release_at']==7300
    row['seeding_time_limit']+=120
    assert forecast(row,{},100)['release_at']==14500


@pytest.mark.parametrize('changes,state',[
    ({'progress':.5},'downloading'),({'state':'stoppedUP'},'paused'),
    ({'share_limit_action':'Stop'},'retained'),({'ratio_only':True},'ratio'),
    ({'seeding_goal_reached':True,'waiting_for_downloaders':True},'waiting'),
    ({'seeding_goal_reached':True,'seeding_auto_extended':True},'extended'),
    ({'seeding_goal_reached':True},'soon'),({'seeding_time':None},'unknown'),
])
def test_conditional_cleanup_has_no_promised_date(changes,state):
    row=torrent();row.update(changes)
    result=forecast(row,{},100)
    assert result['state']==state and result['release_at'] is None


def test_conversion_requires_published_copy_and_uses_its_own_cleanup_rule():
    row=torrent();row.update(seeding_requirement_met=True,waiting_for_downloaders=True)
    assert forecast(row,{'converted':True,'published':False},100)['state']=='processing'
    assert forecast(row,{'converted':True,'published':True},100)['state']=='soon'


def test_schedule_excludes_retained_bytes_and_survives_offline_worker():
    sources=[{'stage':'.incomplete/a','hashes':['rss','v2'],'bytes':8192,'reclaimable_bytes':4096},
             {'stage':'.incomplete/b','hashes':['keep'],'bytes':8192,'reclaimable_bytes':8192}]
    row=torrent();keep=torrent();keep.update(hash='keep',share_limit_action='Stop')
    runtime=Mock();runtime.rpc.return_value={'torrents':[row,keep]}
    result=schedule(sources,runtime,100)
    assert result['scheduled_bytes']==4096
    assert len(result['items'])==2
    runtime.rpc.side_effect=ValueError('private error')
    result=schedule(sources,runtime,100)
    assert not result['available'] and result['scheduled_bytes']==0
    assert all(i['state']=='unknown' for i in result['items'])
    assert 'private error' not in str(result)


def test_schedule_is_bounded_and_prioritises_next_cleanup():
    sources=[{'stage':str(i),'hashes':[str(i)],'bytes':4096,'reclaimable_bytes':4096} for i in range(12)]
    rows=[]
    for i in range(12):
        row=torrent();row.update(hash=str(i),seeding_time=i*3600);rows.append(row)
    runtime=Mock();runtime.rpc.return_value={'torrents':rows}
    result=schedule(sources,runtime,100)
    assert result['count']==12 and len(result['items'])==10
    assert len(result['timeline'])==12  # The summary includes downloads beyond the detail limit.
    assert sum(p['bytes'] for p in result['timeline'])==12*4096
    assert result['items'][0]['release_at']<result['items'][-1]['release_at']
