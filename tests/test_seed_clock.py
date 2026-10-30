import pytest
import json
import time
import green_credit
from green_credit import CreditLedger
from qbit_rpc import seeding_completion, SEEDING_SECONDS

@pytest.mark.parametrize('action',['Stop','RemoveWithContent'])
def test_move_time_frozen_across_pollers_restart_and_completion(action,monkeypatch):
    tick=[100.0]
    monkeypatch.setattr('green_credit.time.monotonic',lambda:tick[0])
    row={'hash':'a'*40,'added_on':1,'seeding_time':100,'state':'stalledUP',
         'share_limit_action':action,'ratio_limit':2,'ratio':0,'num_leechs':0,'upspeed':0}
    def sample(raw,state):
        tick[0]+=10
        green_credit.publish_seed_health(True,'test-session')
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
def test_manual_pause_freezes_seed_time_even_if_native_counter_grows(state,action,monkeypatch):
    tick=[100.0]
    monkeypatch.setattr('green_credit.time.monotonic',lambda:tick[0])
    row={'hash':'b'*40,'added_on':1,'state':'stalledUP','share_limit_action':action}
    def sample(raw,status):
        tick[0]+=10
        green_credit.publish_seed_health(True,'test-session')
        row.update(seeding_time=raw,state=status)
        with CreditLedger().transaction() as ledger:
            return ledger.update(row)['seeding_time']
    assert sample(100,'stalledUP')==100
    assert sample(110,'stalledUP')==110
    assert sample(120,state)==110
    assert sample(3720,state)==110
    assert sample(3730,'stalledUP')==110
    assert sample(3740,'stalledUP')==120


@pytest.fixture
def sample_clock(monkeypatch):
    tick=[100.0]
    monkeypatch.setattr('green_credit.time.monotonic',lambda:tick[0])
    def sample(raw, *, seconds=10, state='stalledUP', ready=True,
               session='client-a', heartbeat=True, vpn=True, vpn_age=0):
        tick[0]+=seconds
        if heartbeat:
            green_credit.publish_seed_health(ready,session)
        green_credit.VPN_STATUS.write_text(json.dumps({
            'healthy':vpn,'checked_at':time.time()-vpn_age,'relay_enabled':False}))
        row={'hash':'c'*40,'added_on':1,'seeding_time':raw,'state':state,
             'share_limit_action':'RemoveWithContent','ratio':0,'ratio_limit':1}
        with CreditLedger().transaction() as ledger:
            return ledger.update(row)['seeding_time']
    return sample


def test_vpn_disconnect_freezes_clock_before_qbittorrent_has_stopped(sample_clock):
    assert sample_clock(100)==100
    assert sample_clock(110)==110
    assert sample_clock(120,vpn=False)==110
    assert sample_clock(3720,seconds=3600,vpn=False)==110
    assert sample_clock(3730)==110  # Recovery only establishes a baseline.
    assert sample_clock(3740)==120


def test_supervisor_unavailable_and_qbittorrent_restart_never_catch_up(sample_clock):
    assert sample_clock(100)==100
    assert sample_clock(110)==110
    assert sample_clock(120,ready=False)==110
    assert sample_clock(3600,seconds=3600,ready=False)==110
    assert sample_clock(3700,session='client-b')==110
    assert sample_clock(3710,session='client-b')==120
    # An abrupt restart can change session without a final offline sample.
    assert sample_clock(4000,session='client-c')==120
    assert sample_clock(4010,session='client-c')==130


def test_stale_heartbeat_and_long_sampling_gap_are_not_seed_time(sample_clock):
    assert sample_clock(100)==100
    assert sample_clock(110)==110
    assert sample_clock(130,seconds=20,heartbeat=False)==110
    assert sample_clock(140)==110
    assert sample_clock(150)==120
    assert sample_clock(3750,seconds=3600)==120
    assert sample_clock(3760)==130


def test_short_outage_without_an_offline_torrent_sample_still_breaks_interval(sample_clock):
    assert sample_clock(100)==100
    assert sample_clock(110)==110
    green_credit.pause_seed_health()
    assert sample_clock(120)==110
    assert sample_clock(130)==120


def test_recovered_heartbeat_does_not_hide_a_supervisor_stall(sample_clock):
    assert sample_clock(100)==100
    # A refreshed heartbeat cannot prove seeding during the preceding stale gap.
    assert sample_clock(116,seconds=16)==100
    assert sample_clock(126)==110


@pytest.mark.parametrize('age',[15,3600,-10])
def test_stale_or_future_vpn_status_freezes_clock(sample_clock,age):
    assert sample_clock(100)==100
    assert sample_clock(110,vpn_age=age)==100
    assert sample_clock(120)==100
    assert sample_clock(130)==110


@pytest.mark.parametrize('raw',['{broken','[]'])
def test_unreadable_health_evidence_freezes_and_can_recover(sample_clock,raw):
    assert sample_clock(100)==100
    green_credit.SEED_HEALTH.write_text(raw)
    assert sample_clock(110,heartbeat=False)==100
    assert sample_clock(120)==100
    assert sample_clock(130)==110


def test_rpc_transport_failure_invalidates_clock_even_if_worker_has_not_polled(sample_clock,monkeypatch):
    from unittest.mock import Mock
    import requests
    import qbit_rpc
    assert sample_clock(100)==100
    client=Mock()
    client.__enter__=Mock(return_value=client);client.__exit__=Mock(return_value=False)
    client.request.side_effect=requests.Timeout('synthetic outage')
    monkeypatch.setattr(qbit_rpc.requests,'Session',Mock(return_value=client))
    with pytest.raises(requests.Timeout):qbit_rpc.call('torrents/info')
    assert json.loads(green_credit.SEED_HEALTH.read_text())['ready'] is False
    assert sample_clock(110)==100
    assert sample_clock(120)==110


@pytest.mark.parametrize('state',['checkingUP','checkingDL','checkingResumeData',
    'queuedUP','downloading','stalledDL','missingFiles','error','unknown','moving'])
def test_only_actual_seeding_states_earn_time(sample_clock,state):
    assert sample_clock(100)==100
    assert sample_clock(110,state=state)==100
    assert sample_clock(3710,seconds=3600,state=state)==100
    assert sample_clock(3720)==100
    assert sample_clock(3730)==110


def test_counter_jump_is_bounded_by_monotonic_elapsed_time(sample_clock):
    assert sample_clock(100)==100
    assert sample_clock(10000,seconds=10)==110
    assert sample_clock(5)==110  # Rolled-back checkpoint establishes a new baseline.
    assert sample_clock(15)==120


def test_interleaved_polls_do_not_lose_verified_time_between_integer_ticks(sample_clock):
    assert sample_clock(100)==100
    assert sample_clock(100,seconds=9)==100
    assert sample_clock(110,seconds=1)==110
    assert sample_clock(110,seconds=0)==110


def test_invalid_counter_breaks_continuity(sample_clock):
    assert sample_clock(100)==100
    assert sample_clock(float('nan'))==100
    assert sample_clock(3720)==100
    assert sample_clock(3730)==110


def test_unverified_initial_sample_does_not_import_offline_native_time(sample_clock):
    assert sample_clock(3600,ready=False)==0
    assert sample_clock(3700)==0
    assert sample_clock(3710)==10


def test_outage_cannot_push_torrent_over_49_hour_deletion_goal(sample_clock):
    assert sample_clock(SEEDING_SECONDS-5)==SEEDING_SECONDS-5
    credit={'seeding_time':sample_clock(SEEDING_SECONDS+1000,vpn=False),
            'ratio':0,'ratio_limit':1}
    row={'state':'stalledUP','share_limit_action':'RemoveWithContent','num_leechs':0,'upspeed':0}
    assert not seeding_completion(row,credit)['seeding_goal_reached']
