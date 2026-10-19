import copy
import threading
from unittest.mock import Mock

from app import create_app
from test_app import FakeRuntime,login
from trackers import Trackers

HASH='a'*40
META={'hashes':[HASH],'name':'Release'}
CONFIG={'provider':'nordicbytes','name':'Demo','api_key':'fixture-not-real-key'}
POSTER='https://image.tmdb.org/t/p/w500/fixture.jpg'


def test_manual_refresh_bypasses_failure_cache_and_recovers_poster(tmp_path):
    trackers=Trackers(tmp_path);ident=trackers.save(CONFIG)
    benefits=trackers.benefits
    benefits.request(META)
    cached=next(iter(benefits.cache.values()))
    cached['result']={'status':'unavailable','matches':[]}
    benefits.remember(META,cached['result'])
    assert benefits.snapshot(META)['status']=='unavailable'
    before=benefits.jobs.qsize()
    assert benefits.refresh_snapshot(META)['status']=='pending'
    assert benefits.jobs.qsize()==before+1
    assert benefits.refresh_snapshot(META)['status']=='pending'
    assert benefits.jobs.qsize()==before+1
    stop=threading.Event()
    found={'status':'matched','matches':[{'tracker_id':ident,'created_at':None,
        'poster':POSTER,'freeleech':100}]}
    def lookup(*args):
        stop.set();return found
    benefits.lookup=Mock(side_effect=lookup)
    benefits.run(stop)
    assert benefits.snapshots[HASH]==found
    restored=Trackers(tmp_path)
    assert restored.benefits.snapshots[HASH]['matches'][0]['poster']==POSTER


def test_refresh_preserves_verified_accounting_and_only_enriches_poster(tmp_path):
    trackers=Trackers(tmp_path);ident=trackers.save(CONFIG)
    benefits=trackers.benefits
    old={'status':'matched','matches':[{'tracker_id':ident,'created_at':'2023-01-01T00:00:00Z',
        'freeleech':25,'poster':None}]}
    benefits.remember(META,old)
    policy=(tmp_path/'rpc'/'green-policy.json').read_bytes()
    benefits.remember(META,{'status':'unavailable','matches':[]})
    assert benefits.snapshots[HASH]==old
    fresh=copy.deepcopy(old)
    fresh['matches'][0].update(poster=POSTER,created_at=None,freeleech=100)
    benefits.remember(META,fresh)
    match=benefits.snapshots[HASH]['matches'][0]
    assert match['poster']==POSTER and match['created_at']==old['matches'][0]['created_at']
    assert match['freeleech']==25
    assert (tmp_path/'rpc'/'green-policy.json').read_bytes()==policy


def test_metadata_refresh_is_authenticated_csrf_protected_and_uses_existing_torrent(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    endpoint='/api/torrents/'+HASH+'/refresh-metadata'
    assert app.test_client().post(endpoint).status_code==403
    client,headers=login(app)
    assert client.post(endpoint).status_code==403
    runtime=app.extensions['runtime']
    runtime.status=Mock(return_value={'ready':False,'torrents_available':True,
        'torrents':[{'hash':HASH,'name':'Actual release'}]})
    benefits=app.extensions['trackers'].benefits
    benefits.refresh_snapshot=Mock(return_value={'status':'pending'})
    result=client.post(endpoint,headers=headers,json={'name':'attacker-controlled','url':'https://untrusted.test'})
    assert result.status_code==200 and result.json['benefits']['status']=='pending'
    benefits.refresh_snapshot.assert_called_once_with({'hashes':[HASH,None,None],'name':'Actual release'})
    runtime.rpc.assert_not_called()
    assert client.post('/api/torrents/'+'b'*40+'/refresh-metadata',headers=headers).status_code==404
    assert client.post('/api/torrents/invalid/refresh-metadata',headers=headers).status_code==400
    runtime.status.return_value={'torrents_available':False,'torrents':[]}
    assert client.post(endpoint,headers=headers).status_code==503
    runtime.status.return_value={'torrents_available':True,'torrents':[{'hash':HASH,'name':''}]}
    assert client.post(endpoint,headers=headers).status_code==409
