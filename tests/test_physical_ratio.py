import json
from unittest.mock import Mock

import pytest
import green_credit
from green_credit import CreditLedger, initial_ratio_limit, real_ratio
from qbit_rpc import finish_seeding, stop_requirement

HASH='f'*40


@pytest.mark.parametrize('ratio,credited,met',[(1,.5,True),(.5,2,False)])
def test_account_credit_never_controls_stop_or_deletion(ratio,credited,met):
    row={'hash':HASH,'ratio':ratio,'credited_ratio':credited,'uploaded':ratio*1000,'downloaded':1000,
         'share_limit_action':'RemoveWithContent','state':'stalledUP','num_leechs':0,'upspeed':0,'seeding_time':1}
    assert stop_requirement(row)['seeding_requirement_met'] is met
    api=Mock()
    result=finish_seeding(api,row,{'ratio':ratio,'credited_ratio':credited,'ratio_limit':1,'ratio_only':True})
    assert bool(result) is met
    assert api.called is met


@pytest.mark.parametrize('known,until',[(False,None),(True,2000),(True,None)])
def test_new_and_saved_goals_are_never_scaled_by_green(known,until):
    green_credit.POLICIES.write_text(json.dumps({'_enabled':True,HASH:{'known':known,'until':until}}))
    assert initial_ratio_limit([HASH],2.5,now=1000)==2.5
    row={'hash':HASH,'uploaded':1000,'downloaded':1000,'ratio':0,'ratio_limit':5,'added_on':900}
    with CreditLedger().transaction() as ledger:
        result=ledger.update(row,now=1100)
    assert result['ratio_limit']==result['native_ratio_limit']==2.5
    assert result['ratio']==1  # The byte counters are the source of truth.


def test_old_credit_forecast_is_retrained_without_changing_goal_or_seed_clock():
    with CreditLedger().transaction() as ledger:
        ledger.register([HASH],3,adaptive=True)
        ledger.entries[HASH]['upload_potential']={'at':1000,'since':0,'uploaded':100,'credited':50,'rate':100000000,'last_upload':1000}
        ledger.entries[HASH]['seed_clock']={'raw':100,'seconds':90,'moving':False,'paused':False}
    row={'hash':HASH,'uploaded':200,'downloaded':1000,'state':'stalledUP','seeding_time':110,
         'share_limit_action':'RemoveWithContent','num_complete':1,'num_incomplete':100}
    with CreditLedger().transaction() as ledger:
        result=ledger.update(row,now=1010)
        assert ledger.entries[HASH]['upload_potential']['basis']=='physical-upload-v2'
    # Upgrading a legacy clock preserves its total and takes a fresh baseline.
    assert result['ratio_limit']==3 and result['seeding_time']==90
    assert not result['seeding_upload_potential']


def test_credit_is_not_a_fallback_for_missing_physical_counters():
    assert real_ratio({'credited_ratio':10})==0
    assert real_ratio({'ratio':float('nan'),'credited_ratio':10})==0
