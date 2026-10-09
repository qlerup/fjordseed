import json
from unittest.mock import Mock

import pytest

from app import create_app
from test_app import FakeRuntime, login
from trackers import Trackers

KEY='fixture-key-not-a-real-key'
CONFIG={'provider':'nordicbytes','name':'NordicBytes','api_key':KEY}
ACCOUNT={'username':'fixture','stats':{'uploaded':4000,'downloaded':2000,'ratio':2,'buffer':2000,
         'warnings':{'hnr':1,'manual':2}},'events':{'global':[{'title':'Freeleech','ends_at':'2030-01-01'}]}}


def test_credential_storage_and_key_preservation(tmp_path):
    trackers=Trackers(tmp_path)
    ident=trackers.save(CONFIG)
    assert KEY not in json.dumps(trackers.public())
    assert trackers.entries()[0]['api_key']==KEY
    trackers.save({**CONFIG,'id':ident,'name':'Renamed','api_key':''})
    assert trackers.entries()[0]['api_key']==KEY
    assert trackers.public()['trackers'][0]['name']=='Renamed'
    restored=Trackers(tmp_path)
    assert restored.entries()[0]['api_key']==KEY
    restored.remove(ident)
    assert restored.public()['trackers']==[]


@pytest.mark.parametrize('data', [None, [], {}, {**CONFIG,'provider':'https://localhost'},
    {**CONFIG,'provider':[]}, {**CONFIG,'api_key':'bad\nkey'}, {**CONFIG,'api_key':''},
    {**CONFIG,'id':'missing'},{**CONFIG,'name':'x'*81}])
def test_invalid_tracker_is_rejected(tmp_path,data):
    with pytest.raises(ValueError):
        Trackers(tmp_path).save(data)


def test_cached_stats_outage_key_change_and_removal_race(tmp_path):
    trackers=Trackers(tmp_path)
    ident=trackers.save(CONFIG)
    trackers.fetch=Mock(return_value={'username':'fixture','stats':ACCOUNT['stats'],'events':[]})
    trackers.refresh()
    assert trackers.public()['trackers'][0]['status']=='ok'
    trackers.fetch.side_effect=ValueError('secret '+KEY)
    trackers.refresh()
    item=trackers.public()['trackers'][0]
    assert item['status']=='error' and item['stats']['ratio']==2 and item['updated_at']
    assert KEY not in json.dumps(item)
    trackers.save({**CONFIG,'id':ident,'api_key':'replacement-test-key'})
    assert 'stats' not in trackers.public()['trackers'][0]
    def deleted_during_fetch(entry):
        trackers.remove(entry['id'])
        return {'stats':ACCOUNT['stats']}
    trackers.fetch.side_effect=deleted_during_fetch
    trackers.refresh()
    assert trackers.public()['trackers']==[] and not trackers.cache


def test_fetch_uses_fixed_host_header_no_redirect_and_allowlist(tmp_path,monkeypatch):
    response=Mock(status_code=200)
    response.iter_content.return_value=[json.dumps({**ACCOUNT,'api_key':KEY}).encode()]
    response.__enter__=Mock(return_value=response)
    response.__exit__=Mock(return_value=False)
    client=Mock()
    client.__enter__=Mock(return_value=client)
    client.__exit__=Mock(return_value=False)
    client.get.return_value=response
    monkeypatch.setattr('trackers.requests.Session',Mock(return_value=client))
    result=Trackers.fetch(CONFIG)
    assert result['stats']['warnings']==3
    assert 'api_key' not in result
    assert client.get.call_args.args[0]=='https://nordicbytes.org/api/user'
    assert client.get.call_args.kwargs['allow_redirects'] is False
    assert client.get.call_args.kwargs['headers']['Authorization']=='Bearer '+KEY
    response.status_code=403
    with pytest.raises(ValueError,match='rettigheder'):
        Trackers.fetch(CONFIG)
    response.status_code=302
    with pytest.raises(ValueError):
        Trackers.fetch(CONFIG)
    response.status_code=200
    response.iter_content.return_value=[b'x'*(1024*1024+1)]
    with pytest.raises(ValueError,match='stort'):
        Trackers.fetch(CONFIG)


def test_api_auth_csrf_and_no_key_echo(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    assert app.test_client().get('/api/trackers').status_code==401
    client,headers=login(app)
    assert client.post('/api/trackers',json=CONFIG).status_code==403
    response=client.post('/api/trackers',headers=headers,json=CONFIG)
    assert response.status_code==200 and KEY not in response.text
    ident=response.json['id']
    app.extensions['trackers'].fetch=Mock(return_value={'stats':ACCOUNT['stats'],'username':'fixture','events':[]})
    app.extensions['trackers'].refresh()
    public=client.get('/api/trackers')
    assert public.json['trackers'][0]['stats']['ratio']==2
    assert KEY not in public.text
    assert client.post('/api/trackers/'+ident+'/delete',headers=headers).status_code==200


@pytest.mark.parametrize('value,expected',[(0,0),(12.5,12.5),(None,None),('12.5',None),(True,None),(float('inf'),None)])
def test_shards_preserves_zero_fraction_and_missing_value(monkeypatch,value,expected):
    monkeypatch.setattr(Trackers,'read_json',Mock(return_value={**ACCOUNT,'stats':{**ACCOUNT['stats'],'shards':value}}))
    assert Trackers.fetch(CONFIG)['stats']['shards']==expected


def test_missing_shards_is_not_reported_as_zero(monkeypatch):
    monkeypatch.setattr(Trackers,'read_json',Mock(return_value=ACCOUNT))
    assert Trackers.fetch(CONFIG)['stats']['shards'] is None
