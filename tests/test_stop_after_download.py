from unittest.mock import Mock

import pytest

from green_credit import CreditLedger
from qbit_rpc import execute, finish_seeding, share_policy, sync_share_limits
from rss import validate_feed

HASH = 'd' * 40


@pytest.mark.parametrize('state,progress,stops', [
    ('downloading', .99, False), ('downloading', 1, False),
    ('uploading', 1, True), ('stalledUP', 1, True), ('forcedUP', 1, True),
    ('stalledUP', .99, False), ('moving', 1, False), ('queuedUP', 1, True),
    ('stoppedUP', 1, False), ('pausedUP', 1, False),
])
def test_stop_only_complete_active_torrents_and_never_delete(state, progress, stops):
    api = Mock()
    row = {'hash': HASH, 'state': state, 'progress': progress,
           'share_limit_action': 'Stop', 'num_leechs': 5, 'upspeed': 1000000}
    assert not finish_seeding(api, row, {'stop_on_complete': True})
    if stops:
        api.assert_called_once_with('torrents/stop', {'hashes': HASH})
    else:
        api.assert_not_called()


def test_add_persists_before_download_and_edits_can_opt_out(monkeypatch):
    row = {'hash': HASH, 'state': 'downloading', 'ratio_limit': -1,
           'share_limit_action': 'Stop'}
    def api(path, data=None, files=None):
        if path == 'torrents/add':
            with CreditLedger().transaction() as ledger:
                assert ledger.update(row)['stop_on_complete'] is True
        return Mock(text='Ok.', json=lambda: {'current_network_interface': 'tun0', 'upnp': False}
                    if path == 'app/preferences' else [row])
    call = Mock(side_effect=api)
    monkeypatch.setattr('qbit_rpc.call', call)
    execute('add', {'magnet': 'magnet:?xt=urn:btih:' + HASH, 'ratio_action': 'stop_keep'})
    assert call.call_args.args[1]['shareLimitAction'] == 'Stop'
    assert call.call_args.args[1]['ratioLimit'] == -1
    execute('ratio', {'hash': HASH, 'ratio_limit': 2})
    with CreditLedger().transaction() as ledger:
        assert ledger.update(row)['stop_on_complete'] is True
    execute('ratio', {'hash': HASH, 'ratio_limit': 2, 'ratio_action': 'keep'})
    with CreditLedger().transaction() as ledger:
        assert ledger.update(row)['stop_on_complete'] is False
    execute('ratio', {'hash': HASH, 'ratio_action': 'stop_keep'})
    with CreditLedger().transaction() as ledger:
        assert ledger.update(row)['stop_on_complete'] is True


def test_worker_stops_without_browser_and_keeps_durable_policy(monkeypatch):
    row = {'hash': HASH, 'state': 'uploading', 'progress': 1,
           'share_limit_action': 'Stop', 'ratio_limit': -1,
           'seeding_time_limit': -1, 'inactive_seeding_time_limit': -1}
    with CreditLedger().transaction() as ledger:
        ledger.register([HASH], 1, stop_on_complete=True)
    api = Mock(return_value=Mock(json=lambda: [row]))
    def publish(api, rows):
        # Retained files may move into the library only after the stop request.
        assert api.call_args.args == ('torrents/stop', {'hashes': HASH})
        return []
    monkeypatch.setattr('download_storage.publish_complete', publish)
    sync_share_limits(api)
    assert api.call_args_list[-1].args == ('torrents/stop', {'hashes': HASH})
    with CreditLedger().transaction() as ledger:
        assert ledger.update(row)['stop_on_complete'] is True
    row['state'] = 'stoppedUP'
    api.reset_mock()
    monkeypatch.setattr('download_storage.publish_complete', lambda api, rows: [])
    sync_share_limits(api)
    assert [c.args[0] for c in api.call_args_list] == ['torrents/info']


def test_policy_and_rss_do_not_require_ratio():
    assert share_policy({'ratio_action': 'stop_keep', 'ratio_limit': ''}) == {
        'ratio_action': 'stop_keep', 'ratio_limit': 1.0}
    feed = validate_feed({'name': 'Fixture', 'url': 'https://tracker.example/rss',
                          'folder': '', 'enabled': True, 'ratio_action': 'stop_keep'})
    assert feed['ratio_action'] == 'stop_keep'
