import json
from unittest.mock import Mock
import pytest
import rss
import rss_gate
from app import create_app
from test_app import FakeRuntime,login
from torrent_meta import torrent_meta


def feed(**changes):
    return {"id":"a"*32,"name":"Sized feed","url":"https://tracker.example/rss",
            "enabled":True,"include":"","folder":"","ratio_limit":1,"ratio_action":"keep",
            "max_size_gb":8.5,"required_badges":[],"min_leechers":0,"tracker_id":"",**changes}


@pytest.mark.parametrize('value',[-1,'nan','inf',True,None,[],{},1000001,'bad'])
def test_invalid_limits_rejected(value):
    with pytest.raises(ValueError):rss.validate_feed(feed(max_size_gb=value))


def test_size_boundaries_unknown_and_decimal_limits():
    rule=feed();maximum=int(8.5*1024**3)
    for size,expected in [(maximum-1,True),(maximum,True),(maximum+1,False),
                          (None,False),('1',False),(True,False),(-1,False)]:
        assert rss.size_matches({'size':size},rule) is expected
    assert rss.size_matches({},feed(max_size_gb=0))
    assert rss.validate_feed(feed(max_size_gb='8.5'))['max_size_gb']==8.5
    assert rss.validate_feed(feed(max_size_gb=''))['max_size_gb']==0
    # Sum all files before comparing: neither individual file is over 1 GB.
    raw=b'd4:infod5:filesld6:lengthi700000000eed6:lengthi700000000eee4:name4:test6:pieces0:ee'
    meta=torrent_meta(raw)
    assert meta['size']==1400000000
    assert not rss.size_matches(meta,feed(max_size_gb=1))


def test_size_filter_disables_native_auto_download_without_requiring_api(tmp_path,monkeypatch):
    calls=[]
    def api(path,data=None):
        calls.append((path,data));return Mock(json=lambda:{})
    monkeypatch.setattr(rss,'folder_path',lambda _:tmp_path)
    rss.sync_rss([feed()],api)
    rule=json.loads(next(d['ruleDef'] for p,d in calls if p=='rss/setRule'))
    assert rule['enabled'] is False
    assert json.loads(calls[-1][1]['json'])['rss_auto_downloading_enabled'] is False


def gate_fixture(tmp_path,monkeypatch,sizes,**requirements):
    rule=feed(**requirements);name=rss.PREFIX+rule['id'];calls=[]
    (tmp_path/'fjord-rss.json').write_text(json.dumps([rule]))
    articles=[{'title':str(i),'torrentURL':'https://tracker.example/'+str(i),'id':str(i)} for i in range(len(sizes))]
    def api(path,data=None,files=None):
        calls.append((path,data))
        payload={}
        if path=='rss/rules':payload={name:{'enabled':False,'mustContain':'','affectedFeeds':[rule['url']]}}
        elif path.startswith('rss/items'):payload={name:{'url':rule['url'],'articles':articles}}
        elif path.startswith('rss/matchingArticles'):payload={name:[a['title'] for a in articles]}
        elif path.startswith('torrents/info'):payload=[]
        return Mock(json=lambda:payload,text='Ok.')
    def metadata(url):
        i=int(url.rsplit('/',1)[1]);ident=f'{i+1:040x}'
        return {'hashes':[ident],'size':sizes[i]}, {'magnet':'magnet:?xt=urn:btih:'+ident}
    monkeypatch.setattr(rss_gate,'fetch_metadata',metadata)
    monkeypatch.setattr(rss_gate,'folder_path',lambda _:tmp_path/'downloads')
    request={'feed_id':rule['id'],'revision':rss_gate.fingerprint(rule)}
    def invoke(action,**data):return rss_gate.gate_rpc(action,{**request,**data},api,tmp_path)
    return invoke,calls,rule


def test_prepare_skips_oversize_unknown_then_adds_boundary_without_tracker(tmp_path,monkeypatch):
    invoke,calls,_=gate_fixture(tmp_path,monkeypatch,[int(8.5*1024**3)+1,None,int(8.5*1024**3)])
    candidate=invoke('rss_prepare')
    assert candidate['meta']['hashes']==[f'{3:040x}']
    assert not any(p=='torrents/add' for p,d in calls)
    invoke('rss_resolve',token=candidate['token'],hashes=candidate['meta']['hashes'],approved=True)
    added=[d for p,d in calls if p=='torrents/add']
    assert len(added)==1 and added[0]['ratioLimit']==1 and added[0]['forceStart']=='false'
    assert not invoke('rss_prepare')


def test_commit_rechecks_size_and_feed_revision(tmp_path,monkeypatch):
    invoke,calls,rule=gate_fixture(tmp_path,monkeypatch,[1024])
    candidate=invoke('rss_prepare')
    path=tmp_path/('rss-pending-'+rule['id']+'.json')
    pending=json.loads(path.read_text());pending['meta']['size']=int(8.5*1024**3)+1
    path.write_text(json.dumps(pending))
    with pytest.raises(ValueError,match='size'):invoke('rss_resolve',token=candidate['token'],approved=True)
    rule['max_size_gb']=1;(tmp_path/'fjord-rss.json').write_text(json.dumps([rule]))
    with pytest.raises(ValueError,match='Feed changed'):invoke('rss_resolve',token=candidate['token'],approved=True)
    assert not any(p=='torrents/add' for p,d in calls)


def test_api_roundtrip_size_only_and_parent_gate_requires_no_key(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    client,headers=login(app)
    data=feed();data.pop('id')
    saved=client.post('/api/rss',headers=headers,json=data)
    assert saved.status_code==200
    public=client.get('/api/rss').json['feeds'][0]
    assert public['max_size_gb']==8.5
    data.update(id=saved.json['id'],url='',max_size_gb=5)
    assert client.post('/api/rss',headers=headers,json=data).status_code==200
    assert client.get('/api/rss').json['feeds'][0]['max_size_gb']==5
    state=app.extensions['state'];state.save('b'*32,True)
    runtime=app.extensions['runtime']
    runtime.rpc.side_effect=[{'token':'candidate','meta':{'hashes':['c'*40],'size':1024}}, {'ok':True}]
    gate=rss_gate.RssGate(app.extensions['rss'],runtime,app.extensions['trackers'],state)
    gate.tick()
    assert runtime.rpc.call_args_list[-1].args[0]=='rss_resolve'
    assert runtime.rpc.call_args_list[-1].args[1]['approved'] is True


def test_size_and_badges_must_both_match_before_add(tmp_path,monkeypatch):
    import time
    invoke,calls,_=gate_fixture(tmp_path,monkeypatch,[1024],tracker_id='b'*32,required_badges=['freeleech'])
    candidate=invoke('rss_prepare')
    approval={'token':candidate['token'],'hashes':candidate['meta']['hashes'],'approved':True}
    with pytest.raises(ValueError,match='Badges'):
        invoke('rss_resolve',**approval,benefits={'status':'matched','checked_at':time.time(),'matches':[{'tracker_id':'b'*32,'freeleech':50}]})
    assert not any(p=='torrents/add' for p,d in calls)
    invoke('rss_resolve',**approval,benefits={'status':'matched','checked_at':time.time(),'matches':[{'tracker_id':'b'*32,'freeleech':100}]})
    assert len([p for p,d in calls if p=='torrents/add'])==1
