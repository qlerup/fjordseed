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
    assert args[1]['seedingTimeLimit']==args[1]['inactiveSeedingTimeLimit']==-1
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
