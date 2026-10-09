import base64
import io
from unittest.mock import Mock

import pytest

from qbit_rpc import execute, share_policy
from test_app import login


@pytest.mark.parametrize('value', ['nan', 'inf', '-0.1', '10001', 'oops', None, True])
def test_invalid_ratio_rejected(value):
    with pytest.raises(ValueError):
        share_policy({'ratio_limit':value})


def test_delete_requires_explicit_finite_ratio():
    with pytest.raises(ValueError):
        share_policy({'ratio_action':'delete'})
    with pytest.raises(ValueError):
        share_policy({'ratio_limit':2,'ratio_action':'anything'})
    assert share_policy({}) == {'ratio_limit':-1,'ratio_action':'keep'}


@pytest.mark.parametrize('method', ['magnet','torrent'])
@pytest.mark.parametrize('action,expected', [('keep','Stop'),('delete','RemoveWithContent')])
def test_add_sets_native_per_torrent_policy_before_start(monkeypatch,method,action,expected):
    call=Mock(side_effect=[Mock(json=lambda:{'current_network_interface':'tun0','upnp':False}),Mock(text='Ok.')])
    monkeypatch.setattr('qbit_rpc.call',call)
    payload={'ratio_limit':2.5,'ratio_action':action,method:
             'magnet:?xt=urn:btih:'+'a'*40 if method=='magnet' else base64.b64encode(b'd4:infodee').decode()}
    execute('add',payload)
    args=call.call_args.args
    assert args[0]=='torrents/add'
    assert args[1]['ratioLimit']==2.5
    assert args[1]['shareLimitAction']==expected
    assert args[1]['seedingTimeLimit']==2880
    assert args[1]['inactiveSeedingTimeLimit']==-1
    assert args[1]['stopped']=='false'


def test_http_policy_validation_before_rpc(tmp_path):
    from app import create_app
    from test_app import FakeRuntime
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    client,headers=login(app)
    app.extensions['state'].save('a'*32,True)
    magnet='magnet:?xt=urn:btih:'+'a'*40
    for policy in ({'ratio_limit':'nan'}, {'ratio_action':'delete'}, {'ratio_limit':'1','ratio_action':'invalid'}):
        assert client.post('/api/torrents',headers=headers,data={'magnet':magnet,**policy}).status_code==400
    app.extensions['runtime'].rpc.assert_not_called()
    assert client.post('/api/torrents',headers=headers,data={'torrent':(io.BytesIO(b'd4:infodee'),'test.torrent'),
        'ratio_limit':'0','ratio_action':'delete'}).status_code==200
    assert app.extensions['runtime'].rpc.call_args.args[1]['ratio_limit']==0


@pytest.mark.parametrize('result,accepted', [
    ({'success_count':1,'pending_count':0,'failure_count':0},True),
    ({'success_count':0,'pending_count':1,'failure_count':0},True),
    ({'success_count':0,'pending_count':0,'failure_count':1},False),
    ({},False),
])
def test_qbit_52_json_add_response(monkeypatch,result,accepted):
    call=Mock(side_effect=[Mock(json=lambda:{'current_network_interface':'tun0','upnp':False}),
                          Mock(text='{}',json=lambda:result)])
    monkeypatch.setattr('qbit_rpc.call',call)
    if accepted:
        assert execute('add',{'magnet':'magnet:?xt=urn:btih:'+'a'*40})=={'ok':True}
    else:
        with pytest.raises(ValueError):
            execute('add',{'magnet':'magnet:?xt=urn:btih:'+'a'*40})


@pytest.mark.parametrize('ratio,seconds,met',[(.99,172799,False),(1,0,True),(.1,172800,True),
    (1,172800,True),(None,None,False),(.5,-1,False),(float('nan'),0,False)])
def test_manual_warning_uses_one_to_one_or_48_hours_independent_of_selected_ratio(ratio,seconds,met):
    from qbit_rpc import stop_requirement
    assert stop_requirement({'ratio':ratio,'seeding_time':seconds,'ratio_limit':5})['seeding_requirement_met'] is met


@pytest.mark.parametrize('action',['stop','delete'])
def test_early_manual_action_requires_explicit_ack_but_is_allowed(monkeypatch,action):
    from qbit_rpc import SeedingRequirementError
    calls=[]
    row={'hash':'a'*40,'ratio':.2,'seeding_time':3600,'ratio_limit':5}
    def api(path,data=None):
        calls.append((path,data))
        return Mock(json=lambda:{'current_network_interface':'tun0','upnp':False} if path=='app/preferences' else [row])
    monkeypatch.setattr('qbit_rpc.call',api)
    with pytest.raises(SeedingRequirementError):execute(action,{'hash':'a'*40})
    assert not any(p=='torrents/'+action for p,d in calls)
    execute(action,{'hash':'a'*40,'confirm_early_stop':True})
    assert calls[-1][0]=='torrents/'+action
    if action=='delete':assert calls[-1][1]['deleteFiles']=='false'
    row['ratio']=1
    execute(action,{'hash':'a'*40})
    assert calls[-1][0]=='torrents/'+action


def test_existing_limits_gain_48_hours_preserve_actions_and_higher_ratio():
    from qbit_rpc import sync_share_limits
    calls=[]
    def api(path,data=None):
        calls.append((path,data));return Mock(json=lambda:[
            {'hash':'a'*40,'ratio_limit':0,'seeding_time_limit':-1,'share_limit_action':'Stop'},
            {'hash':'b'*40,'ratio_limit':3,'seeding_time_limit':-1,'share_limit_action':'RemoveWithContent'},
            {'hash':'c'*40,'ratio_limit':2,'seeding_time_limit':2880,'inactive_seeding_time_limit':-1}])
    sync_share_limits(api)
    updates=[d for p,d in calls if p=='torrents/setShareLimits']
    assert len(updates)==2 and updates[0]['ratioLimit']==1 and updates[1]['ratioLimit']==3
    assert updates[1]['shareLimitAction']=='RemoveWithContent'
    assert all(d['seedingTimeLimit']==2880 and d['inactiveSeedingTimeLimit']==-1 for d in updates)
