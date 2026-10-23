import pytest
from green_credit import CreditLedger
from qbit_rpc import seeding_completion, SEEDING_SECONDS

@pytest.mark.parametrize('action',['Stop','RemoveWithContent'])
def test_move_time_frozen_across_pollers_restart_and_completion(action):
    row={'hash':'a'*40,'added_on':1,'seeding_time':100,'state':'stalledUP',
         'share_limit_action':action,'ratio_limit':2,'ratio':0,'num_leechs':0,'upspeed':0}
    def sample(raw,state):
        row.update(seeding_time=raw,state=state)
        with CreditLedger().transaction() as ledger:
            return ledger.update(row)
    assert sample(100,'stalledUP')['seeding_time']==100
    assert sample(110,'stalledUP')['seeding_time']==110
    assert sample(120,'moving')['seeding_time']==110
    assert sample(150,'moving')['seeding_time']==110
    assert sample(150,'moving')['seeding_time']==110
    assert sample(160,'stalledUP')['seeding_time']==110
    assert sample(170,'stalledUP')['seeding_time']==120
    assert sample(170,'stoppedUP')['seeding_time']==120
    assert sample(170,'stoppedUP')['seeding_time']==120
    assert sample(5,'stalledUP')['seeding_time']==120
    assert sample(15,'stalledUP')['seeding_time']==130


def test_native_move_time_cannot_trigger_49_hour_deletion():
    row={'state':'stalledUP','seeding_time':SEEDING_SECONDS+100,
         'share_limit_action':'RemoveWithContent','num_leechs':0,'upspeed':0}
    credit={'seeding_time':SEEDING_SECONDS-1,'ratio':0,'ratio_limit':1}
    assert not seeding_completion(row,credit)['seeding_goal_reached']
    credit['seeding_time']+=1
    assert seeding_completion(row,credit)['seeding_goal_reached']


@pytest.mark.parametrize('state',['pausedUP','pausedDL','stoppedUP','stoppedDL'])
@pytest.mark.parametrize('action',['Stop','RemoveWithContent'])
def test_manual_pause_freezes_seed_time_even_if_native_counter_grows(state,action):
    row={'hash':'b'*40,'added_on':1,'state':'stalledUP','share_limit_action':action}
    def sample(raw,status):
        row.update(seeding_time=raw,state=status)
        with CreditLedger().transaction() as ledger:
            return ledger.update(row)['seeding_time']
    assert sample(100,'stalledUP')==100
    assert sample(110,'stalledUP')==110
    assert sample(120,state)==110
    assert sample(3720,state)==110
    assert sample(3730,'stalledUP')==110
    assert sample(3740,'stalledUP')==120
