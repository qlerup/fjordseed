import json
from unittest.mock import Mock
import pytest
from qbit_rpc import DOWNLOAD_QUEUE_PREFERENCES, normalize_forced_downloads, sync_download_queue, prioritize_rss_downloads, download_queue_summary


def test_migrates_old_defaults_to_shared_eight_download_queue():
    before={'queueing_enabled':True,'max_active_downloads':3,'max_active_uploads':3,
            'max_active_torrents':5,'dont_count_slow_torrents':True}
    api=Mock(side_effect=[Mock(),Mock(json=lambda:DOWNLOAD_QUEUE_PREFERENCES)])
    sync_download_queue(before,api)
    policy=json.loads(api.call_args_list[0].args[1]['json'])
    assert policy=={'queueing_enabled':True,'max_active_downloads':8,'max_active_uploads':-1,
                    'max_active_torrents':-1,'dont_count_slow_torrents':False}
    assert api.call_args_list[0].args[0]=='app/setPreferences'
    assert all(not c.args[0].startswith('torrents/') for c in api.call_args_list)


def test_policy_is_idempotent_and_checks_actual_applied_preferences():
    api=Mock()
    sync_download_queue(dict(DOWNLOAD_QUEUE_PREFERENCES),api)
    api.assert_not_called()
    api.side_effect=[Mock(),Mock(json=lambda:{})]
    with pytest.raises(RuntimeError,match='not applied'):
        sync_download_queue({},api)


def test_only_forced_incomplete_torrents_lose_the_queue_bypass():
    rows=[{'hash':str(i),'state':state} for i,state in enumerate(
        ['forcedDL','forcedMetaDL','forcedUP','stoppedDL','pausedDL','queuedDL','uploading','stalledUP'])]
    api=Mock()
    normalize_forced_downloads(api,rows)
    api.assert_called_once_with('torrents/setForceStart',{'hashes':'0|1','value':'false'})
    api.reset_mock()
    normalize_forced_downloads(api,rows[2:])
    api.assert_not_called()


def test_rss_first_preserves_order_and_never_starts_paused_or_seeders():
    rows=[{'hash':str(i),'priority':i,'state':'queuedDL','tags':'FjordSeed-RSS-feed' if i in (1,3) else ''} for i in range(5)]
    rows += [{'hash':'paused','priority':5,'state':'stoppedDL','tags':'FjordSeed-RSS-feed'},
             {'hash':'seed','priority':-1,'state':'uploading','tags':'FjordSeed-RSS-feed'}]
    api=Mock();prioritize_rss_downloads(api,rows)
    assert [c.args for c in api.call_args_list]==[('torrents/topPrio',{'hashes':'3'}),('torrents/topPrio',{'hashes':'1'})]
    # Simulate native topPrio movements and verify stable ordering/idempotency.
    order=list(rows[:5])
    for c in api.call_args_list:
        moved=next(r for r in order if r['hash']==c.args[1]['hashes']);order.remove(moved);order.insert(0,moved)
    assert [r['hash'] for r in order]==['1','3','0','2','4']
    for i,r in enumerate(order):r['priority']=i
    api.reset_mock();prioritize_rss_downloads(api,order);api.assert_not_called()


def test_counter_is_shared_and_seeders_paused_and_errors_use_no_slots():
    rows=[{'state':'stalledDL','tags':'FjordSeed-RSS-feed'}]*5+[{'state':'downloading'}]*3
    rows += [{'state':'queuedDL'}]*4+[{'state':s} for s in ('uploading','stalledUP','stoppedDL','error','checkingUP')]
    assert download_queue_summary(rows)=={'active':8,'limit':8,'waiting':4,'rss_active':5,'manual_active':3}
