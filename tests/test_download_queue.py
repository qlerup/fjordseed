import json
from unittest.mock import Mock
import pytest
from qbit_rpc import DOWNLOAD_QUEUE_PREFERENCES, normalize_forced_downloads, sync_download_queue


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
