import json,time
from unittest.mock import Mock
import pytest
import rss,rss_gate
from app import create_app
from test_app import FakeRuntime,login


def feed(**changes):
    return dict(id='a'*32,name='Badge feed',url='https://nordicbytes.org/rss?secret=private',folder='',
        enabled=True,ratio_limit=1,ratio_action='keep',download_from=None,
        required_badges=['freeleech','double_upload'],tracker_id='b'*32) | changes


def result(**flags):
    return {'status':'matched','checked_at':time.time(),'matches':[{'tracker_id':'b'*32,
        'freeleech':100,'double_upload':True,'featured':True,'internal':True,'refundable':True,**flags}]}


@pytest.mark.parametrize('badges',[[],['freeleech'],['double_upload'],list(rss.BADGES)])
def test_optional_badges_all_required_on_one_match(badges):
    f=feed(required_badges=badges)
    assert rss_gate.badges_match(result(),f)
    if not badges:
        assert rss_gate.badges_match({},f);return
    for badge in badges:
        assert not rss_gate.badges_match(result(**{badge:50 if badge=='freeleech' else False}),f)


def test_unknown_stale_wrong_tracker_and_split_matches_rejected():
    for data in ({},{'status':'pending'},result(tracker_id='c'*32),result(freeleech=None),result(freeleech='100')):
        assert not rss_gate.badges_match(data,feed())
    stale=result();stale['checked_at']-=31;assert not rss_gate.badges_match(stale,feed())
    split=result(freeleech=0);split['matches']+=result(double_upload=False)['matches']
    assert not rss_gate.badges_match(split,feed())


@pytest.mark.parametrize('badges',[None,'freeleech',['wrong'],[{}]])
def test_invalid_badges_rejected(badges):
    with pytest.raises(ValueError):rss.validate_feed(feed(required_badges=badges))


def test_api_enforces_active_key_provider_and_retains_requirements_on_pause(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime);client,headers=login(app)
    trackers=app.extensions['trackers'];ident=trackers.save({'provider':'nordicbytes','name':'Account','api_key':'fixture-key-not-real'})
    data=feed(tracker_id=ident);data.pop('id')
    assert client.post('/api/rss',headers=headers,json=data).status_code==400
    trackers.cache[ident]={'status':'ok','updated_at':time.time()}
    wrong={**data,'url':'https://other.example/rss'}
    assert client.post('/api/rss',headers=headers,json=wrong).status_code==400
    saved=client.post('/api/rss',headers=headers,json=data);assert saved.status_code==200
    data.update(id=saved.json['id'],url='');trackers.cache[ident]['status']='error'
    assert client.post('/api/rss',headers=headers,json=data).status_code==400
    data['enabled']=False;assert client.post('/api/rss',headers=headers,json=data).status_code==200
    data.pop('required_badges');data.pop('tracker_id')
    assert client.post('/api/rss',headers=headers,json=data).status_code==200
    assert client.get('/api/rss').json['feeds'][0]['required_badges']==['freeleech','double_upload']


def test_worker_uses_fresh_api_and_rechecks_it_before_commit(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    trackers=app.extensions['trackers'];ident=trackers.save({'provider':'nordicbytes','name':'Account','api_key':'fixture-key-not-real'})
    trackers.cache[ident]={'status':'ok','updated_at':time.time()}
    data=feed(tracker_id=ident);data.pop('id');app.extensions['rss'].save(data)
    app.extensions['state'].save('c'*32,True);runtime=app.extensions['runtime']
    candidate={'token':'candidate','meta':{'hashes':['d'*40],'name':'Linux'}}
    benefits=trackers.benefits;benefits.request=Mock(return_value=result(tracker_id=ident,freeleech=50))
    worker=rss_gate.RssGate(app.extensions['rss'],runtime,app.extensions['state'],benefits)
    runtime.rpc.return_value=candidate;worker.tick()
    assert runtime.rpc.call_args_list[-1].args[1]['approved'] is False
    assert benefits.request.call_args.kwargs['max_age']==30
    runtime.rpc.reset_mock();benefits.request.return_value={'status':'pending'};worker.tick()
    assert len(runtime.rpc.call_args_list)==1
    runtime.rpc.reset_mock();benefits.request.return_value=result(tracker_id=ident);worker.tick()
    assert runtime.rpc.call_args_list[-1].args[1]['approved'] is True
    runtime.rpc.reset_mock();trackers.cache[ident]['status']='error';worker.tick();runtime.rpc.assert_not_called()


def test_vpn_rpc_cannot_bypass_selected_badges(tmp_path,monkeypatch):
    f=feed();name=rss.PREFIX+f['id'];(tmp_path/'fjord-rss.json').write_text(json.dumps([f]));calls=[]
    magnet='magnet:?xt=urn:btih:'+'c'*40+'&dn=Linux'
    def api(path,data=None,files=None):
        calls.append((path,data));payload={}
        if path=='rss/rules':payload={name:{'enabled':False,'mustContain':'','affectedFeeds':[f['url']]}}
        elif path.startswith('rss/items'):payload={name:{'url':f['url'],'articles':[{'id':'post','torrentURL':magnet}]}}
        elif path.startswith('torrents/info'):payload=[]
        return Mock(json=lambda:payload,text='Ok.')
    monkeypatch.setattr(rss_gate,'folder_path',lambda _:tmp_path/'downloads')
    data={'feed_id':f['id'],'revision':rss_gate.fingerprint(f)}
    candidate=rss_gate.gate_rpc('rss_prepare',data,api,tmp_path)
    commit={**data,'token':candidate['token'],'hashes':['c'*40],'approved':True}
    for response in ({},result(freeleech=50),result(double_upload=False)):
        with pytest.raises(ValueError,match='badges'):rss_gate.gate_rpc('rss_resolve',{**commit,'benefits':response},api,tmp_path)
    assert not any(p=='torrents/add' for p,_ in calls)
    rss_gate.gate_rpc('rss_resolve',{**commit,'benefits':result()},api,tmp_path)
    assert len([p for p,_ in calls if p=='torrents/add'])==1
