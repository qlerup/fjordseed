import json
from unittest.mock import Mock

import pytest
import green_credit
from green_credit import CreditLedger
from qbit_rpc import execute, finish_seeding, seeding_completion, share_policy
from rss import validate_feed
from app import create_app
from test_app import FakeRuntime, login

HASH = 'b' * 40


@pytest.mark.parametrize('value', [None, '', 0, -1, True, 'nan', 'inf', 1.5, '1.5', 525601, [], {}])
def test_manual_time_validation(value):
    with pytest.raises(ValueError):
        share_policy({'ratio_action':'delete_time','seed_minutes':value}, manual=True)


def test_manual_only_policy_and_rss_rejection():
    value = {'ratio_action':'delete_time','seed_minutes':'60'}
    assert share_policy(value, manual=True) == {'ratio_action':'delete_time','ratio_limit':1.,'seed_minutes':60}
    with pytest.raises(ValueError, match='manuel'):
        share_policy(value)
    with pytest.raises(ValueError, match='manuel'):
        validate_feed(dict(value, name='Feed', url='https://tracker.example/rss', folder='', enabled=True))


def test_one_hour_deadline_ignores_ratio_and_uploaders_but_requires_active_state():
    row={'hash':HASH,'state':'uploading','share_limit_action':'RemoveWithContent','progress':1,'num_leechs':4,'upspeed':5000}
    credit={'seed_minutes':60,'ratio_limit':1,'ratio':100,'seeding_time':3599}
    api=Mock()
    assert not seeding_completion(row,credit)['seeding_goal_reached']
    assert not finish_seeding(api,row,credit)
    api.assert_not_called()
    credit.update(seeding_time=3600,ratio=0)
    assert seeding_completion(row,credit)['seeding_goal_reached']
    assert not seeding_completion(row,credit)['waiting_for_downloaders']
    assert not finish_seeding(api,{**row,'state':'stoppedUP'},credit)
    assert finish_seeding(api,row,credit)
    api.assert_called_once_with('torrents/delete', {'hashes':HASH,'deleteFiles':'true'})
    from deletion_events import directory
    receipt=json.loads(next(directory().glob('*.json')).read_text())
    assert receipt['event']['reason']=='time'
    assert receipt['event']['seed_hours']==1


def test_manual_policy_survives_restart_offline_and_can_be_changed(monkeypatch):
    tick=[100.]
    monkeypatch.setattr(green_credit.time,'monotonic',lambda:tick[0])
    row={'hash':HASH,'state':'stalledUP','share_limit_action':'RemoveWithContent','ratio_limit':-1,
         'progress':1,'seeding_time':0,'num_leechs':0,'upspeed':0,'added_on':1}
    def api(path,data=None,files=None):
        return Mock(text='Ok.',json=lambda:{'current_network_interface':'tun0','upnp':False} if path=='app/preferences' else [row])
    call=Mock(side_effect=api);monkeypatch.setattr('qbit_rpc.call',call)
    execute('add',{'magnet':'magnet:?xt=urn:btih:'+HASH,'ratio_action':'delete_time','seed_minutes':1})
    assert call.call_args.args[1]['seedingTimeLimit']==-1  # Verified ledger owns time.
    def sample(raw,healthy=True,session='first'):
        tick[0]+=10;row['seeding_time']=raw
        green_credit.publish_seed_health(healthy,session)
        with CreditLedger().transaction() as ledger:return ledger.update(row)
    assert sample(0)['seed_minutes']==1
    assert sample(10)['seeding_time']==10
    assert sample(500,False)['seeding_time']==10
    assert sample(510,session='restarted')['seeding_time']==10
    credit=sample(520,session='restarted')
    assert credit['seeding_time']==20
    assert not seeding_completion(row,credit)['seeding_goal_reached']
    execute('ratio',{'hash':HASH,'ratio_action':'delete_time','seed_minutes':60})
    with CreditLedger().transaction() as ledger:assert ledger.update(row)['seed_minutes']==60
    execute('ratio',{'hash':HASH,'ratio_action':'keep','ratio_limit':1})
    with CreditLedger().transaction() as ledger:assert ledger.update(row)['seed_minutes'] is None
    with pytest.raises(ValueError,match='tilføjelse'):
        execute('ratio',{'hash':HASH,'ratio_action':'delete_time','seed_minutes':60})


def test_add_api_forwards_validated_minutes_and_protects_csrf(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    client,headers=login(app)
    app.extensions['state'].save('test-vpn',True)
    runtime=app.extensions['runtime']
    runtime.status=Mock(return_value={'ready':True})
    value={'magnet':'magnet:?xt=urn:btih:'+HASH,'ratio_action':'delete_time','seed_minutes':'60'}
    assert client.post('/api/torrents',data=value).status_code==403
    assert client.post('/api/torrents',data=dict(value,seed_minutes='0'),headers=headers).status_code==400
    runtime.rpc.assert_not_called()
    assert client.post('/api/torrents',data=value,headers=headers).status_code==200
    assert runtime.rpc.call_args.args[1]['seed_minutes']==60
