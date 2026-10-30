from unittest.mock import Mock
import pytest
from green_credit import CreditLedger
from qbit_rpc import execute, seeding_completion, extra_seed_hours

@pytest.mark.parametrize('value',[-1,8761,True,None,'1',float('nan'),float('inf')])
def test_invalid_extra_hours(value):
    with pytest.raises(ValueError):extra_seed_hours(value)


def test_extra_time_survives_restart_and_delays_time_goal(monkeypatch):
    row={'hash':'a'*40,'state':'stalledUP','ratio':0,'ratio_limit':1,
         'seeding_time':49*3600,'share_limit_action':'RemoveWithContent','num_leechs':0,'upspeed':0}
    api=Mock(side_effect=lambda path,data=None:Mock(json=lambda:
        {'current_network_interface':'tun0','upnp':False} if path=='app/preferences' else [row]))
    monkeypatch.setattr('qbit_rpc.call',api)
    execute('ratio',{'hash':row['hash'],'ratio_limit':1,'extra_seed_hours':1})
    with CreditLedger().transaction() as ledger:credit=ledger.update(row)
    assert credit['extra_seed_hours']==1
    assert not seeding_completion(row,credit)['seeding_goal_reached']
    row['seeding_time']=50*3600
    # Simulate an already verified hour, not an instantaneous native counter jump.
    with CreditLedger().transaction() as ledger:
        ledger.entries[row['hash']]['seed_clock']['seconds']+=3600
    with CreditLedger().transaction() as ledger:credit=ledger.update(row)
    assert seeding_completion(row,credit)['seeding_goal_reached']
    execute('ratio',{'hash':row['hash'],'ratio_limit':2})
    with CreditLedger().transaction() as ledger:assert ledger.update(row)['extra_seed_hours']==1
    execute('ratio',{'hash':row['hash'],'ratio_limit':2,'extra_seed_hours':0})
    with CreditLedger().transaction() as ledger:assert ledger.update(row)['extra_seed_hours']==0
    assert not any(c.args[0] in ('torrents/start','torrents/stop','torrents/delete') for c in api.call_args_list)
