import math
from unittest.mock import Mock

import pytest

import green_credit
from green_credit import CreditLedger
from qbit_rpc import SEEDING_SECONDS, finish_seeding, seeding_completion, sync_share_limits
from seed_potential import MAX_IDLE_SECONDS, upload_potential

GIB=1024**3
MIB=1024**2
HASH='a'*40


def torrent(**changes):
    return {'hash':HASH,'added_on':1,'state':'uploading','share_limit_action':'RemoveWithContent',
            'ratio_limit':1,'ratio':0,'uploaded':0,'downloaded':10*GIB,'seeding_time':0,
            'num_leechs':0,'upspeed':0,'num_incomplete':10,'num_complete':1,**changes}


def trained(row=None, rate=MIB, steps=10):
    row=row or torrent()
    with CreditLedger().transaction() as ledger:
        ledger.register([row['hash']],1,adaptive=True)
    for step in range(steps+1):
        row.update(uploaded=step*60*rate,seeding_time=step*60)
        with CreditLedger().transaction() as ledger:
            credit=ledger.update(row,now=1000+step*60)
    return row,credit


def test_forecast_uses_recent_credited_counter_growth_and_survives_reload():
    row,credit=trained()
    assert credit['seeding_upload_potential']
    assert credit['seeding_predicted_upload']==pytest.approx(MIB*(1-math.exp(-1))*1800)
    assert credit['seeding_predicted_ratio_gain']==pytest.approx(credit['seeding_predicted_upload']/(10*GIB))
    with CreditLedger().transaction() as ledger:
        same=ledger.update(row,now=1600)
    assert same==credit  # Duplicate polls do not inflate or decay the estimate.


@pytest.mark.parametrize('trigger',['ratio','time'])
@pytest.mark.parametrize('ratio_only',[False,True])
def test_forecast_holds_both_goals_but_preserves_original_policy(trigger,ratio_only):
    row,credit=trained()
    credit.update(ratio=1 if trigger=='ratio' else .1,
                  seeding_time=SEEDING_SECONDS if trigger=='time' else 1,ratio_only=ratio_only)
    credit['uploaded']=credit['downloaded']*credit['ratio']
    completion=seeding_completion(row,credit)
    reached=trigger=='ratio' or not ratio_only
    assert completion['seeding_goal_reached'] is reached
    assert completion['seeding_auto_extended'] is reached
    assert not completion['waiting_for_downloaders']  # No current connections or upload.
    api=Mock()
    assert not finish_seeding(api,row,credit)
    api.assert_not_called()
    assert credit['ratio_limit']==1


@pytest.mark.parametrize('source',['','FjordSeed-RSS-'+'b'*32])
@pytest.mark.parametrize('trigger',['ratio','time'])
def test_worker_rechecks_without_browser_then_deletes_when_demand_disappears(monkeypatch,source,trigger):
    row=torrent(tags=source)
    with CreditLedger().transaction() as ledger:
        ledger.register([HASH],1,adaptive=True)
    clock=[1000]
    monkeypatch.setattr(green_credit.time,'time',lambda:clock[0])
    def api(path,data=None):
        if path=='torrents/setShareLimits':
            row.update(ratio_limit=-1,seeding_time_limit=-1,inactive_seeding_time_limit=-1)
        return Mock(json=lambda:[dict(row)])
    api=Mock(side_effect=api)
    sync_share_limits(api)
    for step in range(1,11):
        clock[0]+=60
        row.update(uploaded=step*60*MIB,seeding_time=step*60,upspeed=MIB,num_leechs=1)
        sync_share_limits(api)
    row.update(upspeed=0,num_leechs=0,state='stalledUP')
    if trigger=='ratio':row['uploaded']=row['downloaded']
    else:
        row['seeding_time']=SEEDING_SECONDS
        # Simulate an already earned total, rather than inventing 49h in one tick.
        with CreditLedger().transaction() as ledger:
            ledger.entries[HASH]['seed_clock']['seconds']=SEEDING_SECONDS
    sync_share_limits(api)
    assert not any(call.args[0]=='torrents/delete' for call in api.call_args_list)
    with CreditLedger().transaction() as ledger:
        credit=ledger.update(row)
        assert seeding_completion(row,credit)['seeding_auto_extended']
        assert ledger.entries[HASH]['target']==1
    row['num_incomplete']=0
    clock[0]+=10
    sync_share_limits(api)
    assert api.call_args.args==('torrents/delete',{'hashes':HASH,'deleteFiles':'true'})


def test_forecast_decays_and_stops_extending_even_if_tracker_demand_stays_high():
    row,credit=trained()
    previous=credit['seeding_predicted_upload']
    for elapsed in range(60,MAX_IDLE_SECONDS+61,60):
        with CreditLedger().transaction() as ledger:
            credit=ledger.update(row,now=1600+elapsed)
        assert credit['seeding_predicted_upload']<=previous
        previous=credit['seeding_predicted_upload']
    assert not credit['seeding_upload_potential']
    credit['ratio']=1
    credit['uploaded']=credit['downloaded']
    assert finish_seeding(Mock(),row,credit)


@pytest.mark.parametrize('changes',[{'num_incomplete':0},{'num_complete':10000},{}])
def test_low_recent_upload_or_demand_does_not_extend(changes):
    row,credit=trained(torrent(**changes),rate=1 if not changes else MIB)
    assert not credit['seeding_upload_potential']
    credit['ratio']=1
    credit['uploaded']=credit['downloaded']
    assert finish_seeding(Mock(),row,credit)


@pytest.mark.parametrize('state',['pausedUP','stoppedUP','moving','queuedUP','checkingUP','downloading'])
def test_nonseeding_state_clears_forecast_and_never_resumes(state):
    row,credit=trained()
    row.update(state=state)
    with CreditLedger().transaction() as ledger:
        credit=ledger.update(row,now=1610)
        assert 'upload_potential' not in ledger.entries[HASH]
    assert not credit['seeding_upload_potential']
    assert not finish_seeding(Mock(),row,{**credit,'ratio':1})


@pytest.mark.parametrize('change',[{'uploaded':0},{'share_limit_action':'Stop'},{'added_on':2},
                                 {'uploaded':None},{'uploaded':float('nan')}])
def test_reset_keep_policy_or_invalid_sample_cannot_reuse_potential(change):
    row,credit=trained()
    row.update(change)
    with CreditLedger().transaction() as ledger:
        credit=ledger.update(row,now=1610)
    assert not credit['seeding_upload_potential']


@pytest.mark.parametrize('now',[1590,1800])
def test_clock_rollback_and_long_observation_gap_discard_forecast(now):
    row,credit=trained()
    with CreditLedger().transaction() as ledger:
        credit=ledger.update(row,now=now)
    assert not credit['seeding_upload_potential']


def test_physical_upload_is_forecast_without_green_discount():
    entry={'adaptive_seeding':True}
    row=torrent()
    for step in range(11):
        row['uploaded']=step*60*MIB
        credit=upload_potential(entry,row,10*GIB,1000+step*60)
    assert credit['seeding_predicted_upload']==pytest.approx(MIB*(1-math.exp(-1))*1800)
    previous=credit['seeding_predicted_upload']
    credit=upload_potential(entry,row,10*GIB,1660)
    assert credit['seeding_predicted_upload']<previous


def test_missing_history_high_speed_lifetime_ratio_and_swarm_alone_cannot_extend():
    row=torrent(uploaded=100*GIB,upspeed=100*MIB,ratio=10)
    with CreditLedger().transaction() as ledger:
        credit=ledger.update(row,now=1000)
    assert not credit['seeding_upload_potential']


def test_unknown_tracker_counts_use_recent_measured_upload():
    row,credit=trained(torrent(num_complete=-1,num_incomplete=None))
    assert credit['seeding_upload_potential']


def test_poll_frequency_does_not_change_constant_rate_forecast():
    estimates=[]
    for interval in (4,10,60):
        entry={'adaptive_seeding':True}
        row=torrent()
        for elapsed in range(0,601,interval):
            row['uploaded']=elapsed*MIB
            credit=upload_potential(entry,row,10*GIB,1000+elapsed)
        estimates.append(credit['seeding_predicted_upload'])
    assert estimates==pytest.approx([estimates[0]]*3)


def test_status_exposes_forecast_and_extension_without_changing_goal(monkeypatch):
    from qbit_rpc import execute
    row,credit=trained()
    row['uploaded']=row['downloaded']
    monkeypatch.setattr(green_credit.time,'time',lambda:1600)
    def api(path,data=None):
        if path=='app/preferences':
            return Mock(json=lambda:{'current_network_interface':'tun0','upnp':False,'listen_port':1234})
        if path=='torrents/info':return Mock(json=lambda:[row])
        return Mock(json=lambda:{},text='5.2.4')
    monkeypatch.setattr('qbit_rpc.call',api)
    result=execute('status',{})['torrents'][0]
    assert result['seeding_auto_extended'] is True
    assert result['seeding_predicted_upload']>64*MIB
    assert result['seeding_predicted_ratio_gain']>=.05
    assert result['ratio_limit']==1 and result['seeding_time_limit']==2940
    assert result['num_incomplete']==10 and result['num_complete']==1


def test_existing_delete_policy_does_not_gain_adaptive_behavior():
    row=torrent()
    for step in range(11):
        row.update(uploaded=step*60*MIB,seeding_time=step*60)
        with CreditLedger().transaction() as ledger:
            credit=ledger.update(row,now=1000+step*60)
    assert credit['adaptive_seeding'] is False
    assert credit['seeding_upload_potential'] is False
    credit['ratio']=1
    credit['uploaded']=credit['downloaded']
    assert finish_seeding(Mock(),row,credit)


def test_edit_opt_in_persists_omitted_action_preserves_and_opt_out_clears_forecast(monkeypatch):
    from qbit_rpc import execute
    row=torrent(state='stoppedUP')
    def api(path,data=None):
        return Mock(json=lambda:{'current_network_interface':'tun0','upnp':False} if path=='app/preferences' else [row])
    api=Mock(side_effect=api)
    monkeypatch.setattr('qbit_rpc.call',api)
    execute('ratio',{'hash':HASH,'ratio_limit':1,'ratio_action':'automatic'})
    with CreditLedger().transaction() as ledger:
        credit=ledger.update(row)
    assert credit['adaptive_seeding'] is True and credit['ratio_only'] is False
    execute('ratio',{'hash':HASH,'ratio_limit':2})
    with CreditLedger().transaction() as ledger:
        assert ledger.update(row)['adaptive_seeding'] is True
    execute('ratio',{'hash':HASH,'ratio_limit':2,'ratio_action':'delete'})
    with CreditLedger().transaction() as ledger:
        assert ledger.update(row)['adaptive_seeding'] is False
        assert 'upload_potential' not in ledger.entries[HASH]
    assert not any(c.args[0] in ('torrents/start','torrents/stop','torrents/delete') for c in api.call_args_list)
