from unittest.mock import Mock
import pytest
from green_credit import CreditLedger
from qbit_rpc import execute, initial_managed_ratio, seeding_completion, finish_seeding, SEEDING_SECONDS
from rss import validate_feed

HASH='c'*40


def test_ratio_only_ignores_elapsed_time_but_respects_ratio_and_active_downloaders():
    row={'hash':HASH,'state':'stalledUP','share_limit_action':'RemoveWithContent','num_leechs':0,'upspeed':0}
    credit={'ratio_only':True,'ratio_limit':2,'credited_ratio':1.9,'seeding_time':SEEDING_SECONDS*10}
    api=Mock()
    assert not seeding_completion(row,credit)['seeding_goal_reached']
    assert not finish_seeding(api,row,credit)
    api.assert_not_called()
    credit['credited_ratio']=2
    row['num_leechs']=1
    assert seeding_completion(row,credit)['waiting_for_downloaders']
    assert not finish_seeding(api,row,credit)
    row['num_leechs']=0
    assert finish_seeding(api,row,credit)
    api.assert_called_once_with('torrents/delete',{'hashes':HASH,'deleteFiles':'true'})


def test_default_timed_deletion_still_finishes_after_49_hours():
    row={'state':'stalledUP','share_limit_action':'RemoveWithContent','num_leechs':0,'upspeed':0}
    credit={'ratio_limit':2,'credited_ratio':0,'seeding_time':SEEDING_SECONDS}
    assert seeding_completion(row,credit)['seeding_goal_reached']
    assert not seeding_completion({**row,'share_limit_action':'Stop'},credit)['seeding_goal_reached']


def test_manual_add_persists_ratio_only_before_start_and_edit_can_switch_it(monkeypatch):
    row={'hash':HASH,'ratio_limit':-1,'share_limit_action':'RemoveWithContent','state':'stoppedUP'}
    def api(path,data=None,files=None):
        return Mock(text='Ok.',json=lambda: {'current_network_interface':'tun0','upnp':False} if path=='app/preferences' else [row])
    call=Mock(side_effect=api)
    monkeypatch.setattr('qbit_rpc.call',call)
    execute('add',{'magnet':'magnet:?xt=urn:btih:'+HASH,'ratio_limit':2,'ratio_action':'delete_ratio'})
    assert call.call_args.args[1]['shareLimitAction']=='RemoveWithContent'
    assert call.call_args.args[1]['seedingTimeLimit']==-1
    with CreditLedger().transaction() as ledger:
        assert ledger.update(row)['ratio_only'] is True
    execute('ratio',{'hash':HASH,'ratio_limit':3})
    with CreditLedger().transaction() as ledger:
        assert ledger.update(row)['ratio_only'] is True
    execute('ratio',{'hash':HASH,'ratio_limit':3,'ratio_action':'delete'})
    with CreditLedger().transaction() as ledger:
        assert ledger.update(row)['ratio_only'] is False


def test_rss_policy_validates_and_shared_startup_persists_ratio_only():
    policy=validate_feed({'name':'Fixture','url':'https://tracker.example/rss','folder':'','enabled':True,
                         'ratio_limit':2,'ratio_action':'delete_ratio'})
    assert policy['ratio_action']=='delete_ratio'
    initial_managed_ratio([HASH],2,ratio_only=True)
    with CreditLedger().transaction() as ledger:
        assert ledger.update({'hash':HASH,'state':'downloading'})['ratio_only'] is True
