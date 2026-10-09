import json
import time
from unittest.mock import Mock

import pytest

from app import create_app
import rss
import rss_gate
from test_app import FakeRuntime,login


def feed():
    return dict(id='a'*32,name='Linux',url='https://nordicbytes.org/rss?key=private',folder='',
                enabled=True,include='Linux',ratio_limit=2,ratio_action='keep',
                tracker_id='b'*32,required_badges=['freeleech','double_upload'])


def result(**flags):
    return {'status':'matched','checked_at':time.time(),'matches':[{
        'tracker_id':'b'*32,'freeleech':100,'double_upload':True,**flags}]}


@pytest.mark.parametrize('flags', [dict(freeleech=50),dict(double_upload=False),
    dict(double_upload=None),dict(tracker_id='c'*32)])
def test_all_badges_same_tracker_and_full_freeleech(flags):
    assert rss_gate.badges_match(result(),feed())
    assert not rss_gate.badges_match(result(**flags),feed())


def test_unknown_stale_and_split_matches_never_approve():
    assert not rss_gate.badges_match({'status':'pending'},feed())
    stale=result();stale['checked_at']-=301
    assert not rss_gate.badges_match(stale,feed())
    split=result(freeleech=0);split['matches']+=result(double_upload=False)['matches']
    assert not rss_gate.badges_match(split,feed())


@pytest.mark.parametrize('count,approved',[(49,False),(50,True),(51,True),(None,False),('50',False),(True,False)])
def test_minimum_leechers_inclusive_with_and_without_badges(count,approved):
    entry={**feed(),'min_leechers':50}
    assert rss_gate.badges_match(result(leechers=count),entry) is approved
    entry['required_badges']=[]
    assert rss_gate.badges_match(result(leechers=count,freeleech=0,double_upload=False),entry) is approved
    entry['required_badges']=['freeleech']
    assert not rss_gate.badges_match(result(leechers=50,freeleech=50),entry)


def test_leechers_need_recent_data_from_same_tracker():
    entry={**feed(),'required_badges':[],'min_leechers':50}
    stale=result(leechers=50);stale['checked_at']-=31
    assert not rss_gate.badges_match(stale,entry)
    assert not rss_gate.badges_match(result(leechers=50,tracker_id='c'*32),entry)


@pytest.mark.parametrize('minimum',[-1,1.5,True,None,'50.5',1000001])
def test_invalid_minimum_rejected(minimum):
    with pytest.raises(ValueError):rss.validate_feed({**feed(),'min_leechers':minimum})


def test_minimum_requires_tracker_and_disables_native_download(tmp_path,monkeypatch):
    entry={**feed(),'required_badges':[],'min_leechers':50}
    with pytest.raises(ValueError):rss.validate_feed({**entry,'tracker_id':''})
    calls=[]
    def api(path,data=None):
        calls.append((path,data));return Mock(json=lambda:{})
    monkeypatch.setattr(rss,'folder_path',lambda _:tmp_path)
    rss.sync_rss([entry],api)
    rule=json.loads(next(d['ruleDef'] for p,d in calls if p=='rss/setRule'))
    assert rule['enabled'] is False
    assert json.loads(calls[-1][1]['json'])['rss_auto_downloading_enabled'] is False


def test_gated_rules_cannot_download_natively(tmp_path,monkeypatch):
    calls=[]
    def api(path,data=None):
        calls.append((path,data));return Mock(json=lambda:{})
    monkeypatch.setattr(rss,'folder_path',lambda _:tmp_path)
    rss.sync_rss([feed()],api)
    rule=json.loads(next(d['ruleDef'] for p,d in calls if p=='rss/setRule'))
    assert rule['enabled'] is False
    prefs=json.loads(calls[-1][1]['json'])
    assert prefs['rss_processing_enabled'] is True
    assert prefs['rss_auto_downloading_enabled'] is False


@pytest.mark.parametrize('badges',[None,'freeleech',['fake'],[{}]])
def test_invalid_badges_rejected(badges):
    entry=feed();entry['required_badges']=badges
    with pytest.raises(ValueError):rss.validate_feed(entry)


def test_api_requires_verified_key_and_same_provider(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    client,headers=login(app)
    entry=feed();entry.pop('id')
    assert client.post('/api/rss',headers=headers,json=entry).status_code==400
    trackers=app.extensions['trackers']
    ident=trackers.save({'provider':'nordicbytes','name':'Tracker','api_key':'fixture-key-123456'})
    entry['tracker_id']=ident
    assert client.post('/api/rss',headers=headers,json=entry).status_code==400
    trackers.cache[ident]={'status':'ok','updated_at':time.time()}
    assert client.get('/api/trackers').json['trackers'][0]['badge_ready'] is True
    saved=client.post('/api/rss',headers=headers,json=entry)
    assert saved.status_code==200
    minimum_only={**entry,'name':'Minimum only','url':'https://nordicbytes.org/rss?other=fixture','required_badges':[],'min_leechers':50}
    minimum_saved=client.post('/api/rss',headers=headers,json=minimum_only)
    assert minimum_saved.status_code==200
    assert any(f.get('min_leechers')==50 for f in client.get('/api/rss').json['feeds'])
    entry['id']=saved.json['id'];entry['url']=''
    trackers.cache[ident]['status']='error'
    assert client.get('/api/trackers').json['trackers'][0]['badge_ready'] is False
    assert client.post('/api/rss',headers=headers,json=entry).status_code==400
    entry['enabled']=False
    assert client.post('/api/rss',headers=headers,json=entry).status_code==200
    assert client.get('/api/rss').json['feeds'][0]['required_badges']==['freeleech','double_upload']
    trackers.cache[ident]={'status':'ok','updated_at':time.time()-601}
    assert trackers.badge_ready(ident) is False


@pytest.fixture
def gate(tmp_path,monkeypatch):
    entry=feed();name=rss.PREFIX+entry['id'];calls=[]
    (tmp_path/'fjord-rss.json').write_text(json.dumps([entry]))
    magnet='magnet:?xt=urn:btih:'+'c'*40+'&dn=Linux'
    items={name:{'url':entry['url'],'articles':[{'id':'article','title':'Linux','torrentURL':magnet}]}}
    def api(path,data=None,files=None):
        calls.append((path,data))
        payload={}
        if path=='rss/rules':payload={name:{'enabled':False,'mustContain':'Linux','affectedFeeds':[entry['url']]}}
        elif path.startswith('rss/items'):payload=items
        elif path.startswith('rss/matchingArticles'):payload={name:['Linux']}
        elif path.startswith('torrents/info'):payload=[]
        return Mock(json=lambda:payload,text='Ok.')
    monkeypatch.setattr(rss_gate,'folder_path',lambda _:tmp_path/'downloads')
    data={'feed_id':entry['id'],'revision':rss_gate.fingerprint(entry)}
    def invoke(action,**kwargs):return rss_gate.gate_rpc(action,{**data,**kwargs},api,tmp_path)
    return invoke,calls,tmp_path,items


def test_prepare_does_not_add_and_verified_commit_preserves_policy(gate):
    invoke,calls,root,items=gate
    candidate=invoke('rss_prepare')
    assert candidate['meta']['hashes']==['c'*40]
    assert not any(p=='torrents/add' for p,d in calls)
    # Changed enclosure must never replace the exact candidate we verified.
    next(iter(items.values()))['articles'][0]['torrentURL']='magnet:?xt=urn:btih:'+'d'*40
    invoke('rss_resolve',token=candidate['token'],hashes=['c'*40],approved=True,benefits=result())
    payload=next(d for p,d in calls if p=='torrents/add')
    assert 'c'*40 in payload['urls'] and 'd'*40 not in payload['urls']
    assert payload['ratioLimit']==2 and payload['shareLimitAction']=='Stop'
    assert payload['tags']=='FjordSeed-RSS-'+'a'*32
    assert str(root/'downloads')==payload['savepath']


def test_missing_badges_identity_or_changed_feed_never_add(gate):
    invoke,calls,root,_=gate
    candidate=invoke('rss_prepare')
    with pytest.raises(ValueError):
        invoke('rss_resolve',token=candidate['token'],hashes=['c'*40],approved=True,benefits=result(double_upload=False))
    with pytest.raises(ValueError):
        invoke('rss_resolve',token=candidate['token'],hashes=['d'*40],approved=True,benefits=result())
    entry=feed();entry['enabled']=False
    (root/'fjord-rss.json').write_text(json.dumps([entry]))
    with pytest.raises(ValueError):invoke('rss_resolve',token=candidate['token'],approved=True,benefits=result())
    assert not any(p=='torrents/add' for p,d in calls)


def test_reject_retries_later_and_success_history_survives_restart(gate,monkeypatch):
    invoke,calls,root,_=gate
    candidate=invoke('rss_prepare')
    invoke('rss_resolve',token=candidate['token'],approved=False)
    assert not invoke('rss_prepare')
    assert not any(p=='torrents/add' for p,d in calls)
    later=time.time()+301
    monkeypatch.setattr(rss_gate.time,'time',lambda:later)
    candidate=invoke('rss_prepare')
    invoke('rss_resolve',token=candidate['token'],hashes=['c'*40],approved=True,benefits=result())
    assert not invoke('rss_prepare')
    assert len([p for p,d in calls if p=='torrents/add'])==1


def test_gate_blocks_when_api_access_fails(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    trackers=app.extensions['trackers'];state=app.extensions['state'];runtime=app.extensions['runtime']
    ident=trackers.save({'provider':'nordicbytes','name':'Tracker','api_key':'fixture-key-123456'})
    entry=feed();entry.pop('id');entry['tracker_id']=ident
    app.extensions['rss'].save(entry)
    state.save('d'*32,True)
    worker=rss_gate.RssGate(app.extensions['rss'],runtime,trackers,state)
    worker.tick()
    runtime.rpc.assert_not_called()
