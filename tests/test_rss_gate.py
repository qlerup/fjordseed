import json
import time
from unittest.mock import Mock

import pytest
from app import create_app
import rss
import rss_gate
from test_app import FakeRuntime, login


START='2026-10-07T12:00:00+00:00'


def feed(**changes):
    return dict(id='a'*32,name='Dated feed',url='https://tracker.example/rss?key=private',
                folder='',enabled=True,ratio_limit=2,ratio_action='keep',download_from=START) | changes


@pytest.mark.parametrize('value',[True,123,[],{},'invalid','2026-10-07','2026-10-07T12:00:00','2026-02-30T12:00:00Z'])
def test_invalid_start_rejected(value):
    with pytest.raises(ValueError):rss.validate_feed(feed(download_from=value))


def test_dates_normalized_and_unrestricted_supported():
    assert rss.validate_feed(feed(download_from='2026-10-07T14:00:00+02:00'))['download_from']==START
    for value in (None,''):
        assert rss.validate_feed(feed(download_from=value))['download_from'] is None
        assert rss.date_matches({},feed(download_from=value))


@pytest.mark.parametrize('value,expected',[
    ('2026-10-07T11:59:59Z',False),('2026-10-07T12:00:00Z',True),
    ('2026-10-08T12:00:00Z',True),('2026-10-07T14:00:00+02:00',True),
    ('Wed, 07 Oct 2026 14:00:00 +0200',True),
    (None,False),('',False),('invalid',False),(123,False),('2026-10-08T12:00:00',False)])
def test_inclusive_date_boundary_and_timezone(value,expected):
    assert rss.date_matches({'date':value},feed()) is expected


def test_old_filters_migrate_without_changing_url_history_or_seeding(tmp_path):
    old=feed(include='Linux',max_size_gb=8.5,required_badges=['freeleech'],min_leechers=50,tracker_id='b'*32)
    old.pop('download_from')
    (tmp_path/'rss.json').write_text(json.dumps([old]))
    history=tmp_path/('rss-history-'+old['id']+'.json');history.write_text('{"done":["old"]}')
    store=rss.Rss(tmp_path,tmp_path/'downloads')
    entry=store.entries()[0]
    assert entry['download_from'] is None and entry['url']==old['url'] and entry['ratio_limit']==2
    assert not {'include','max_size_gb','required_badges','min_leechers','tracker_id'} & entry.keys()
    assert json.loads(history.read_text())=={'done':['old']}
    assert json.loads((tmp_path/'rss.json').read_text())==[entry]


@pytest.mark.parametrize('start,gated',[(START,True),(None,False)])
def test_sync_controls_native_download_and_clears_old_filters(tmp_path,monkeypatch,start,gated):
    calls=[];entry=feed(download_from=start);name=rss.PREFIX+entry['id']
    def api(path,data=None):
        calls.append((path,data))
        return Mock(json=lambda:{name:{'mustNotContain':'old','ignoreDays':30,'episodeFilter':'old'}} if path=='rss/rules' else {})
    monkeypatch.setattr(rss,'folder_path',lambda _:tmp_path)
    rss.sync_rss([entry],api)
    rule=json.loads(next(d['ruleDef'] for p,d in calls if p=='rss/setRule'))
    assert rule['enabled'] is (not gated)
    assert rule['mustContain']==rule['mustNotContain']==rule['episodeFilter']=='' and rule['ignoreDays']==0
    prefs=json.loads(calls[-1][1]['json'])
    assert prefs['rss_processing_enabled'] and prefs['rss_auto_downloading_enabled'] is (not gated)


@pytest.fixture
def gate(tmp_path,monkeypatch):
    entry=feed();name=rss.PREFIX+entry['id'];calls=[];fetched=[]
    (tmp_path/'fjord-rss.json').write_text(json.dumps([entry]))
    dates=['2026-10-06T12:00:00Z',None,'bad',START,'2026-10-08T12:00:00Z']
    articles=[{'id':str(i),'title':'Duplicate title','date':date,
               'torrentURL':f'https://tracker.example/{i}'} for i,date in enumerate(dates)]
    def api(path,data=None,files=None):
        calls.append((path,data));payload={}
        if path=='rss/rules':payload={name:{'enabled':False,'mustContain':'','affectedFeeds':[entry['url']]}}
        elif path.startswith('rss/items'):payload={name:{'url':entry['url'],'articles':articles}}
        elif path.startswith('torrents/info'):payload=[]
        return Mock(json=lambda:payload,text='Ok.')
    def metadata(url):
        fetched.append(url);i=int(url.rsplit('/',1)[1]);ident=f'{i+1:040x}'
        return {'hashes':[ident],'name':'Linux'}, {'magnet':'magnet:?xt=urn:btih:'+ident}
    monkeypatch.setattr(rss_gate,'fetch_metadata',metadata)
    monkeypatch.setattr(rss_gate,'folder_path',lambda _:tmp_path/'downloads')
    request={'feed_id':entry['id'],'revision':rss_gate.fingerprint(entry)}
    def invoke(action,**kwargs):return rss_gate.gate_rpc(action,{**request,**kwargs},api,tmp_path)
    return invoke,calls,fetched,articles,tmp_path,entry


def resolve(invoke,candidate):
    return invoke('rss_resolve',token=candidate['token'],hashes=candidate['meta']['hashes'],approved=True)


def test_skip_old_and_undated_before_metadata_then_add_boundary_and_future(gate):
    invoke,calls,fetched,articles,root,entry=gate
    candidate=invoke('rss_prepare')
    assert fetched==['https://tracker.example/3']
    assert not any(p=='torrents/add' for p,d in calls)
    # Changes in a later feed refresh cannot replace prepared torrent metadata.
    articles[3]['torrentURL']='https://tracker.example/999'
    resolve(invoke,candidate)
    added=next(d for p,d in calls if p=='torrents/add')
    assert f'{4:040x}' in added['urls'] and added['forceStart']=='false'
    assert added['ratioLimit']==2 and added['seedingTimeLimit']==2940 and added['shareLimitAction']=='Stop'
    assert added['tags']=='FjordSeed-RSS-'+entry['id'] and added['savepath']==str(root/'downloads')
    articles[3]['torrentURL']='https://tracker.example/3'
    next_candidate=invoke('rss_prepare');resolve(invoke,next_candidate)
    assert fetched==['https://tracker.example/3','https://tracker.example/4']
    assert not invoke('rss_prepare')
    assert len([p for p,d in calls if p=='torrents/add'])==2
    assert [d['articleId'] for p,d in calls if p=='rss/markAsRead']==['3','4']


def test_native_read_history_is_preserved_when_start_date_added(gate):
    invoke,calls,fetched,articles,_,_=gate
    articles[3]['isRead']=True
    candidate=invoke('rss_prepare')
    assert fetched==['https://tracker.example/4']
    resolve(invoke,candidate)
    assert not invoke('rss_prepare')


def test_prepared_before_pause_cannot_add(gate):
    invoke,calls,_,_,root,entry=gate
    candidate=invoke('rss_prepare');entry['enabled']=False
    (root/'fjord-rss.json').write_text(json.dumps([entry]))
    with pytest.raises(ValueError,match='Feed changed'):resolve(invoke,candidate)
    assert not any(p=='torrents/add' for p,d in calls)


def test_changed_start_pause_identity_or_missing_pending_date_never_add(gate):
    invoke,calls,_,_,root,entry=gate
    candidate=invoke('rss_prepare')
    with pytest.raises(ValueError,match='identity'):
        invoke('rss_resolve',token=candidate['token'],hashes=['e'*40],approved=True)
    path=root/('rss-pending-'+entry['id']+'.json');pending=json.loads(path.read_text())
    pending.pop('date');path.write_text(json.dumps(pending))
    with pytest.raises(ValueError,match='date'):resolve(invoke,candidate)
    entry['download_from']='2026-10-09T12:00:00Z';(root/'fjord-rss.json').write_text(json.dumps([entry]))
    with pytest.raises(ValueError,match='Feed changed'):resolve(invoke,candidate)
    assert not any(p=='torrents/add' for p,d in calls)


def test_retry_and_history_persist_after_restart(gate,monkeypatch):
    invoke,calls,_,articles,root,entry=gate
    articles.pop()
    candidate=invoke('rss_prepare');invoke('rss_resolve',token=candidate['token'],approved=False)
    assert not invoke('rss_prepare')
    later=time.time()+301;monkeypatch.setattr(rss_gate.time,'time',lambda:later)
    candidate=invoke('rss_prepare');resolve(invoke,candidate)
    assert not invoke('rss_prepare')
    assert f'{4:040x}' in json.loads((root/('rss-history-'+entry['id']+'.json')).read_text())['done']


def test_api_date_roundtrip_and_gate_needs_no_tracker_key(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime);client,headers=login(app)
    data=feed();data.pop('id')
    assert client.post('/api/rss',json=data).status_code==403
    saved=client.post('/api/rss',headers=headers,json=data);assert saved.status_code==200
    public=client.get('/api/rss').json['feeds'][0]
    assert public['download_from']==START and 'private' not in json.dumps(public)
    data.update(id=saved.json['id'],url='')
    assert client.post('/api/rss',headers=headers,json=data).status_code==200
    assert app.extensions['rss'].entries()[0]['download_from']==START
    state=app.extensions['state'];state.save('b'*32,True);runtime=app.extensions['runtime']
    runtime.rpc.side_effect=[{'token':'candidate','meta':{'hashes':['c'*40]}},{'ok':True}]
    worker=rss_gate.RssGate(app.extensions['rss'],runtime,state);worker.tick()
    assert runtime.rpc.call_args_list[-1].args[0]=='rss_resolve'
    assert runtime.rpc.call_args_list[-1].args[1]['approved'] is True
    data['download_from']=None
    assert client.post('/api/rss',headers=headers,json=data).status_code==200
    assert client.get('/api/rss').json['feeds'][0]['download_from'] is None
