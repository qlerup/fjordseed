import json
from unittest.mock import Mock
import pytest
import rss, rss_gate
from app import create_app
from test_app import FakeRuntime, login
from test_rss_gate import gate, feed, resolve


@pytest.mark.parametrize('value',[0,-1,True,False,1.5,'10',[],{},2**53])
def test_invalid_size_rejected(value):
    with pytest.raises(ValueError):rss.validate_feed(feed(max_size_bytes=value))


def test_inclusive_total_size_and_unknown_metadata():
    f=feed(max_size_bytes=1024**3)
    assert rss.size_matches({'size':1024**3},f)
    assert not rss.size_matches({'size':1024**3+1},f)
    for size in (None,True,-1,'100',100.0):
        assert not rss.size_matches({'size':size},f)
    assert rss.size_matches({},feed())


def test_size_api_roundtrip_partial_edit_and_clear(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    client,headers=login(app);data=feed(max_size_bytes=1536*1024**2);data.pop('id')
    assert client.post('/api/rss',json=data).status_code==403
    saved=client.post('/api/rss',json=data,headers=headers)
    assert saved.status_code==200;ident=saved.json['id']
    assert client.get('/api/rss').json['feeds'][0]['max_size_bytes']==1536*1024**2
    data.update(id=ident,url='');data.pop('max_size_bytes')
    assert client.post('/api/rss',json=data,headers=headers).status_code==200
    assert rss.Rss(tmp_path).entries()[0]['max_size_bytes']==1536*1024**2
    data['max_size_bytes']=None
    assert client.post('/api/rss',json=data,headers=headers).status_code==200
    assert client.get('/api/rss').json['feeds'][0]['max_size_bytes'] is None


@pytest.mark.parametrize('gate',[{'max_size_bytes':1024**3}],indirect=True)
def test_large_candidate_skipped_and_boundary_rechecked_before_add(gate,monkeypatch):
    invoke,calls,fetched,articles,root,entry=gate
    original=rss_gate.fetch_metadata
    def metadata(url):
        meta,payload=original(url)
        meta['size']=1024**3+1 if url.endswith('/3') else 1024**3
        return meta,payload
    monkeypatch.setattr(rss_gate,'fetch_metadata',metadata)
    candidate=invoke('rss_prepare')
    assert fetched==['https://tracker.example/3','https://tracker.example/4']
    assert not any(p=='torrents/add' for p,_ in calls)
    path=root/('rss-pending-'+entry['id']+'.json');pending=json.loads(path.read_text())
    pending['meta']['size']+=1;path.write_text(json.dumps(pending))
    with pytest.raises(ValueError,match='maximum size'):resolve(invoke,candidate)
    assert not any(p=='torrents/add' for p,_ in calls)
    pending['meta']['size']-=1;path.write_text(json.dumps(pending))
    resolve(invoke,candidate)
    assert len([p for p,_ in calls if p=='torrents/add'])==1


@pytest.mark.parametrize('gate',[{'max_size_bytes':1024**4}],indirect=True)
def test_unknown_sizes_cannot_start_or_starve_later_articles(gate):
    invoke,calls,fetched,_,_,_=gate
    assert invoke('rss_prepare')=={'size_skipped':2}
    assert len(fetched)==2
    assert not any(p=='torrents/add' for p,_ in calls)


def test_new_limit_invalidates_already_prepared_candidate(gate):
    invoke,calls,_,_,root,entry=gate
    candidate=invoke('rss_prepare')
    entry['max_size_bytes']=1024**3
    (root/'fjord-rss.json').write_text(json.dumps([entry]))
    with pytest.raises(ValueError,match='Feed changed'):resolve(invoke,candidate)
    assert not any(p=='torrents/add' for p,_ in calls)


def test_manager_rejects_unknown_candidate_from_older_worker(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    store=app.extensions['rss'];entry=feed(max_size_bytes=1024**3);entry.pop('id');store.save(entry)
    app.extensions['state'].save('b'*32,True)
    runtime=app.extensions['runtime'];runtime.rpc=Mock(side_effect=[{'token':'candidate','meta':{'hashes':['c'*40]}},{'ok':True}])
    worker=rss_gate.RssGate(store,runtime,app.extensions['state']);worker.tick()
    assert runtime.rpc.call_args.args[0]=='rss_resolve'
    assert runtime.rpc.call_args.args[1]['approved'] is False
