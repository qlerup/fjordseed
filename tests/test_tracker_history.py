import json
import sqlite3
import time
from unittest.mock import Mock

from app import create_app
from tracker_history import TrackerHistory, RETENTION
from trackers import Trackers
from test_app import FakeRuntime, login
from test_trackers import CONFIG, KEY


def test_persists_independent_account_and_physical_samples(tmp_path):
    now=1_800_000_000
    path=tmp_path/'history.sqlite3';history=TrackerHistory(path)
    history.record('account',{'ratio':4,'credited_uploaded':8000,'credited_downloaded':2000,'api_key':KEY},now)
    history.record('account',{'ratio':3,'credited_uploaded':9000,'credited_downloaded':3000},now+600)
    history.record('seedbox',{'real_uploaded':6000,'real_downloaded':10000},now+600)
    restored=TrackerHistory(path)
    account=restored.samples('account',1,now+601)
    assert [p['ratio'] for p in account]==[4,3]
    assert restored.samples('seedbox',1,now+601)[0]['real_uploaded']==6000
    assert 'real_uploaded' not in account[0]
    assert KEY not in json.dumps(account)


def test_coalesces_samples_ignores_unknowns_and_marks_counter_resets(tmp_path):
    history=TrackerHistory(tmp_path/'h.sqlite3');now=1_800_000_000
    history.record('seedbox',{'real_uploaded':1000,'real_downloaded':2000},now)
    history.record('seedbox',{'real_uploaded':1200,'real_downloaded':2100},now+1)
    assert len(history.samples('seedbox',1,now+2))==1
    history.record('seedbox',{'real_uploaded':50,'real_downloaded':100},now+600)
    history.record('seedbox',{'real_uploaded':60,'real_downloaded':110},now+601)
    reset=history.samples('seedbox',1,now+602)[-1]
    assert reset['real_uploaded_reset'] and reset['real_downloaded_reset']
    history.record('missing',{'ratio':None,'credited_uploaded':True,'real_uploaded':float('nan'),'real_downloaded':-1},now+602)
    assert history.samples('missing',1,now+603)==[]
    history.record('seedbox',{'real_uploaded':500},now+100)
    assert history.samples('seedbox',1,now+602)[-1]==reset


def test_retains_thirty_days_and_preserves_extrema(tmp_path):
    history=TrackerHistory(tmp_path/'h.sqlite3');now=1_800_000_000
    history.record('account',{'ratio':2},now-RETENTION-1)
    history.record('account',{'ratio':3},now)
    assert len(history.samples('account',30,now))==1
    with history.connect() as db:
        rows=[]
        for i in range(1000):
            at=now-1000*600+i*600
            rows.append(('dense',int(at//600),at,json.dumps({'ratio':.2 if i==432 else 9 if i==733 else 2})))
        db.executemany('INSERT INTO samples VALUES (?,?,?,?)',rows)
    points=history.samples('dense',30,now)
    assert len(points)<480
    assert min(p['ratio'] for p in points)==.2 and max(p['ratio'] for p in points)==9


def test_history_api_authorization_periods_and_removal(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    assert app.test_client().get('/api/trackers/unknown/history').status_code==401
    client,headers=login(app);trackers=app.extensions['trackers']
    ident=trackers.save(CONFIG)
    trackers.history.record(ident,{'ratio':2,'credited_uploaded':1000,'credited_downloaded':500})
    trackers.history.record('seedbox',{'real_uploaded':4000,'real_downloaded':8000})
    response=client.get('/api/trackers/'+ident+'/history?days=7')
    assert response.status_code==200
    assert response.json['account'][0]['ratio']==2
    assert response.json['seedbox'][0]['real_uploaded']==4000
    assert KEY not in response.text
    assert client.get('/api/trackers/'+ident+'/history?days=99').status_code==400
    assert client.get('/api/trackers/'+ident+'/history?days=nope').status_code==400
    assert client.get('/api/trackers/missing/history').status_code==404
    trackers.remove(ident)
    assert client.get('/api/trackers/'+ident+'/history').status_code==404
    assert trackers.history.samples(ident,7)==[]
    assert trackers.history.samples('seedbox',7)


def test_failed_account_fetch_never_creates_fake_flat_samples(tmp_path,monkeypatch):
    trackers=Trackers(tmp_path);ident=trackers.save(CONFIG)
    trackers.fetch=Mock(return_value={'stats':{'ratio':4,'uploaded':4000,'downloaded':1000}})
    now=time.time()
    monkeypatch.setattr('trackers.time.time',lambda:now)
    trackers.refresh()
    trackers.fetch.side_effect=RuntimeError('private remote failure')
    monkeypatch.setattr('trackers.time.time',lambda:now+600)
    trackers.refresh()
    assert len(trackers.history.samples(ident,7,now+601))==1
    trackers.save({**CONFIG,'id':ident,'api_key':'another-account-secret'})
    assert trackers.history.samples(ident,7,now+601)==[]


def test_history_rpc_only_reads_allowlisted_global_counters(monkeypatch):
    import qbit_rpc
    call=Mock(side_effect=[Mock(json=lambda:{'current_network_interface':'tun0','upnp':False}),
        Mock(json=lambda:{'server_state':{'alltime_ul':1234,'alltime_dl':5678,'unrelated':'private'}})])
    monkeypatch.setattr(qbit_rpc,'call',call)
    assert qbit_rpc.execute('traffic_history',{})=={'real_uploaded':1234,'real_downloaded':5678}
    assert call.call_args.args==('sync/maindata?rid=0',)


def test_real_history_gaps_survive_downsampling(tmp_path):
    history=TrackerHistory(tmp_path/'h.sqlite3');now=1_800_000_000
    with history.connect() as db:
        db.executemany('INSERT INTO samples VALUES (?,?,?,?)',[
            ('account',i,now-700*600+i*600,json.dumps({'ratio':2+i*.001}))
            for i in range(700) if not 301<=i<313])
    points=history.samples('account',30,now)
    assert len(points)<480
    assert any(point.get('gap_before') for point in points)
