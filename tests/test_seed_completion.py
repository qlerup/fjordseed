import json
from unittest.mock import Mock

import pytest

import green_credit
from qbit_rpc import sync_share_limits, execute, SEEDING_SECONDS


@pytest.mark.parametrize('source', ['', 'FjordSeed-RSS-'+'b'*32])
@pytest.mark.parametrize('trigger', ['ratio', 'time'])
@pytest.mark.parametrize('action', ['Stop', 'RemoveWithContent', 'Remove'])
def test_waits_for_downloaders_then_finishes_after_restart(source,trigger,action):
    row={'hash':'a'*40,'ratio_limit':3,'ratio':3 if trigger=='ratio' else .1,
         'seeding_time':SEEDING_SECONDS if trigger=='time' else 0,
         'state':'uploading','num_leechs':2,'upspeed':500,'share_limit_action':action,'tags':source}
    calls=[]
    def api(path,data=None):
        calls.append((path,data))
        if path=='torrents/setShareLimits':
            # Goal must survive a process crash immediately after this API call.
            saved=json.loads((green_credit.CONFIG/'green-credit.json').read_text())
            assert saved[row['hash']]['target']==3
            row.update(ratio_limit=data['ratioLimit'],seeding_time_limit=data['seedingTimeLimit'],
                       inactive_seeding_time_limit=-1)
        return Mock(json=lambda:[dict(row)])
    def actions():
        return [(p,d) for p,d in calls if p in ('torrents/stop','torrents/delete')]
    sync_share_limits(api)
    assert not actions()
    assert row['ratio_limit']==row['seeding_time_limit']==-1
    row.update(num_leechs=1,upspeed=0,state='stalledUP')
    sync_share_limits(api)  # Reloads ledger from disk, including original goal.
    assert not actions()  # A brief pause in upload must not disconnect a peer.
    row.update(num_leechs=0,upspeed=100)
    sync_share_limits(api)
    assert not actions()
    row['upspeed']=0
    sync_share_limits(api)
    if action=='RemoveWithContent':
        assert actions()==[('torrents/delete',{'hashes':row['hash'],'deleteFiles':'true'})]
    else:
        assert not actions()  # Keep seeding even after both time/ratio goals.
    saved=json.loads((green_credit.CONFIG/'green-credit.json').read_text())
    assert (row['hash'] in saved)==(action!='RemoveWithContent')



@pytest.mark.parametrize('state',['stoppedUP','pausedUP','downloading','checkingUP','queuedUP'])
def test_never_auto_finishes_or_resumes_non_seeding_torrents(state):
    api=Mock(return_value=Mock(json=lambda:[{'hash':'a'*40,'state':state,'ratio':10,
        'ratio_limit':1,'num_leechs':0,'upspeed':0}]))
    sync_share_limits(api)
    assert {c.args[0] for c in api.call_args_list}<= {'torrents/info','torrents/setShareLimits'}


@pytest.mark.parametrize('peers,speed',[(None,0),(-1,0),(0,None),(0,-1),(True,0),(0,float('nan'))])
def test_unknown_peer_data_keeps_seeding(peers,speed):
    api=Mock(return_value=Mock(json=lambda:[{'hash':'a'*40,'state':'stalledUP','ratio':10,
        'ratio_limit':1,'share_limit_action':'RemoveWithContent','num_leechs':peers,'upspeed':speed}]))
    sync_share_limits(api)
    assert not any(c.args[0] in ('torrents/stop','torrents/delete') for c in api.call_args_list)


def test_below_goal_keeps_seeding_without_peers():
    api=Mock(return_value=Mock(json=lambda:[{'hash':'a'*40,'state':'stalledUP','ratio':2.9,
        'ratio_limit':3,'seeding_time':SEEDING_SECONDS-1,'num_leechs':0,'upspeed':0}]))
    sync_share_limits(api)
    assert not any(c.args[0] in ('torrents/stop','torrents/delete') for c in api.call_args_list)


def test_status_explains_waiting_and_keeps_displayed_goal(monkeypatch):
    row={'hash':'a'*40,'state':'uploading','share_limit_action':'RemoveWithContent','ratio':3,'ratio_limit':3,'num_leechs':1,'upspeed':100}
    def api(path,data=None):
        result={'current_network_interface':'tun0','upnp':False,'listen_port':1234} if path=='app/preferences' else [row]
        return Mock(json=lambda:result,text='5.2.1')
    monkeypatch.setattr('qbit_rpc.call',api)
    result=execute('status',{})['torrents'][0]
    assert result['waiting_for_downloaders'] and result['seeding_goal_reached']
    assert result['ratio_limit']==3 and result['seeding_time_limit']==2940


def test_persistence_failure_cannot_disable_existing_limits(monkeypatch):
    api=Mock(return_value=Mock(json=lambda:[{'hash':'a'*40,'ratio_limit':3}]))
    monkeypatch.setattr(green_credit,'atomic',Mock(side_effect=OSError('disk full')))
    with pytest.raises(OSError):sync_share_limits(api)
    assert [c.args[0] for c in api.call_args_list]==['torrents/info']


def test_green_credit_controls_completion_not_raw_ratio(monkeypatch):
    import time
    green_credit.POLICIES.write_text(json.dumps({'_enabled':True,'a'*40:{
        'known':True,'has_date':True,'until':time.time()+3600}}))
    row={'hash':'a'*40,'state':'stalledUP','ratio':1,'ratio_limit':1,
         'share_limit_action':'RemoveWithContent','uploaded':1000,'downloaded':1000,'num_leechs':0,'upspeed':0}
    api=Mock(side_effect=lambda *args:Mock(json=lambda:[dict(row)]))
    sync_share_limits(api)
    assert not any(c.args[0]=='torrents/stop' for c in api.call_args_list)
    row.update(uploaded=2000,ratio=2,ratio_limit=-1)
    sync_share_limits(api)
    assert api.call_args.args==('torrents/delete',{'hashes':row['hash'],'deleteFiles':'true'})


def test_edit_managed_goal_is_durable_without_reenabling_native_limits(monkeypatch):
    from qbit_rpc import initial_managed_ratio
    initial_managed_ratio(['a'*40],2)
    row={'hash':'a'*40,'state':'stoppedUP','ratio_limit':-1,'seeding_time_limit':-1,
         'inactive_seeding_time_limit':-1,'share_limit_action':'Stop'}
    api=Mock(side_effect=lambda path,data=None:Mock(json=lambda:
        {'current_network_interface':'tun0','upnp':False} if path=='app/preferences' else [row]))
    monkeypatch.setattr('qbit_rpc.call',api)
    execute('ratio',{'hash':row['hash'],'ratio_limit':5})
    with green_credit.CreditLedger().transaction() as ledger:
        assert ledger.update(row)['ratio_limit']==5
    assert [c.args[0] for c in api.call_args_list]==['app/preferences','torrents/info?hashes='+row['hash']]
