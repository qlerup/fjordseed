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
    assert not {'include','max_size_gb','min_leechers'} & entry.keys()
    assert entry['required_badges']==['freeleech'] and entry['tracker_id']=='b'*32
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
    assert rule['enabled'] is False
    assert rule['mustContain']==rule['mustNotContain']==rule['episodeFilter']=='' and rule['ignoreDays']==0
    prefs=json.loads(calls[-1][1]['json'])
    assert prefs['rss_processing_enabled'] and prefs['rss_auto_downloading_enabled'] is False


@pytest.fixture
def gate(tmp_path,monkeypatch,request):
    entry=feed(**getattr(request,'param',{}));name=rss.PREFIX+entry['id'];calls=[];fetched=[]
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


@pytest.mark.parametrize('gate',[{'convert':True}],indirect=True)
def test_conversion_disabled_does_not_consume_rss_candidate(gate,monkeypatch):
    invoke,calls,_,_,root,entry=gate
    candidate=invoke('rss_prepare')
    monkeypatch.setattr('conversion.require_enabled',Mock(side_effect=ValueError('GPU disabled')))
    with pytest.raises(ValueError,match='GPU disabled'):resolve(invoke,candidate)
    assert not any(path=='torrents/add' for path,data in calls)
    history=json.loads((root/('rss-history-'+entry['id']+'.json')).read_text())
    assert candidate['token'] not in history['done']


@pytest.mark.parametrize('gate',[{'convert':True,'ratio_action':'stop_keep'}],indirect=True)
def test_converted_rss_uses_buffer_and_fixed_retention(gate,monkeypatch):
    import download_storage as storage
    from pathlib import Path
    invoke,calls,_,_,root,entry=gate
    monkeypatch.setattr('conversion.require_enabled',Mock())
    candidate=invoke('rss_prepare');resolve(invoke,candidate)
    options=next(data for path,data in calls if path=='torrents/add')
    assert options['shareLimitAction']=='RemoveWithContent'
    assert Path(options['savepath']).parent.name=='.incomplete'
    saved=storage.read(storage.CONFIG/'download-storage.json',{})[candidate['meta']['hashes'][0]]
    assert saved['convert'] and saved['conversion_bitrate']==20


def test_rss_downloads_directly_when_streaming_is_disabled(gate,monkeypatch):
    import download_storage as storage
    from pathlib import Path
    invoke,calls,_,_,root,_=gate
    settings=root/'direct-settings.json';settings.write_text('{"streaming_enabled":false}')
    monkeypatch.setattr(storage,'SETTINGS',settings)
    candidate=invoke('rss_prepare');resolve(invoke,candidate)
    options=next(d for p,d in calls if p=='torrents/add')
    assert storage.BUFFER not in Path(options['savepath']).parts
    assert Path(options['savepath']).parent==root/'downloads'
    assert Path(options['savepath']).name=='Linux'


@pytest.mark.parametrize('gate',[{'ratio_action':'delete_ratio'}],indirect=True)
def test_ratio_only_rss_add_stays_in_buffer_and_persists_goal(gate):
    from green_credit import CreditLedger
    from pathlib import Path
    invoke,calls,_,_,root,_=gate
    candidate=invoke('rss_prepare');resolve(invoke,candidate)
    options=next(d for p,d in calls if p=='torrents/add')
    assert options['shareLimitAction']=='RemoveWithContent'
    assert options['seedingTimeLimit']==-1
    assert Path(options['savepath']).parent==root/'downloads'/'.incomplete'
    with CreditLedger().transaction() as ledger:
        assert ledger.update({'hash':candidate['meta']['hashes'][0],'state':'downloading'})['ratio_only'] is True


@pytest.mark.parametrize('gate',[{'ratio_action':'automatic'}],indirect=True)
def test_automatic_rss_add_persists_opt_in_before_start(gate):
    from green_credit import CreditLedger
    invoke,calls,_,_,_,_=gate
    candidate=invoke('rss_prepare');resolve(invoke,candidate)
    options=next(d for p,d in calls if p=='torrents/add')
    assert options['shareLimitAction']=='RemoveWithContent' and options['ratioLimit']==-1
    with CreditLedger().transaction() as ledger:
        credit=ledger.update({'hash':candidate['meta']['hashes'][0],'state':'downloading'})
        assert credit['adaptive_seeding'] is True and credit['ratio_only'] is False


@pytest.mark.parametrize('gate',[{'ratio_action':'stop_keep'}],indirect=True)
def test_stop_after_download_rss_add_preserves_files_and_policy(gate):
    from green_credit import CreditLedger
    invoke,calls,_,_,_,_=gate
    candidate=invoke('rss_prepare');resolve(invoke,candidate)
    options=next(d for p,d in calls if p=='torrents/add')
    assert options['shareLimitAction']=='Stop' and options['ratioLimit']==-1
    with CreditLedger().transaction() as ledger:
        credit=ledger.update({'hash':candidate['meta']['hashes'][0],'state':'downloading'})
        assert credit['stop_on_complete'] is True


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
    assert added['ratioLimit']==-1 and added['seedingTimeLimit']==-1 and added['shareLimitAction']=='Stop'
    assert added['tags']=='FjordSeed-RSS-'+entry['id'] and __import__('pathlib').Path(added['savepath']).parent==root/'downloads'/'.incomplete'
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


def test_successful_add_archives_title_before_torrent_can_disappear(gate):
    from green_credit import CreditLedger
    invoke, calls, _, _, _, entry = gate
    candidate = invoke('rss_prepare')
    resolve(invoke, candidate)
    with CreditLedger().transaction() as ledger:
        item = ledger.entries['_rss_upload']['feeds'][entry['id']]['downloads'][candidate['meta']['hashes'][0]]
        assert item['title'] == 'Linux' and item['credited_uploaded'] == 0


def test_prepared_before_pause_cannot_add(gate):
    invoke,calls,_,_,root,entry=gate
    candidate=invoke('rss_prepare');entry['enabled']=False
    (root/'fjord-rss.json').write_text(json.dumps([entry]))
    with pytest.raises(ValueError,match='Feed changed'):resolve(invoke,candidate)
    assert not any(p=='torrents/add' for p,d in calls)


@pytest.mark.parametrize('gate',[{'title_include':['Badehotellet'],'title_exclude':['Politijagt']}],indirect=True)
def test_title_filters_skip_excluded_before_metadata_and_recheck_before_add(gate):
    invoke,calls,fetched,articles,root,entry=gate
    articles[3]['title']='Politijagt.S01E02'
    articles[4]['title']='Badehotellet_S10E01'
    candidate=invoke('rss_prepare')
    assert fetched==['https://tracker.example/4']
    path=root/('rss-pending-'+entry['id']+'.json')
    pending=json.loads(path.read_text())
    assert pending['title']=='Badehotellet_S10E01'
    pending['title']='Politijagt';path.write_text(json.dumps(pending))
    with pytest.raises(ValueError,match='title filters'):resolve(invoke,candidate)
    assert not any(p=='torrents/add' for p,d in calls)
    pending['title']='Badehotellet_S10E01';path.write_text(json.dumps(pending))
    resolve(invoke,candidate)
    assert len([p for p,d in calls if p=='torrents/add'])==1
    assert not invoke('rss_prepare')


def test_new_title_filter_invalidates_prepared_candidate(gate):
    invoke,calls,_,_,root,entry=gate
    candidate=invoke('rss_prepare')
    entry['title_exclude']=['Duplicate title']
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


@pytest.mark.parametrize('kind,expected', [('green',4),('expired',2),('unknown',4),('own',2)])
def test_manual_and_rss_share_exact_start_policy_and_credit(gate,monkeypatch,kind,expected):
    import green_credit as credit
    import qbit_rpc
    invoke,rss_calls,_,_,_,_=gate
    ident=f'{4:040x}';now=time.time()
    policy={'known':True,'has_date':True,'until':now+3600}
    if kind=='expired':policy['until']=now-3600
    elif kind=='unknown':policy={'known':False,'until':None}
    elif kind=='own':policy['until']=None
    credit.POLICIES.write_text(json.dumps({'_enabled':True,ident:policy}))
    candidate=invoke('rss_prepare');resolve(invoke,candidate)
    rss_options=next(d for p,d in rss_calls if p=='torrents/add')
    manual_calls=[]
    def api(path,data=None,files=None):
        manual_calls.append((path,data));return Mock(json=lambda:{'current_network_interface':'tun0','upnp':False},text='Ok.')
    monkeypatch.setattr(qbit_rpc,'call',api)
    qbit_rpc.execute('add',{'magnet':'magnet:?xt=urn:btih:'+ident+'&dn=Linux','ratio_limit':2,'ratio_action':'keep'})
    manual_options=next(d for p,d in manual_calls if p=='torrents/add')
    for key in ('ratioLimit','seedingTimeLimit','inactiveSeedingTimeLimit','shareLimitAction','forceStart','stopped'):
        assert rss_options[key]==manual_options[key]
    assert rss_options['ratioLimit']==-1
    with credit.CreditLedger().transaction() as ledger:
        result=ledger.update({'hash':ident,'uploaded':1000,'downloaded':1000,'ratio':1,
                              'added_on':now,'ratio_limit':expected},now=now+1)
    assert result['ratio_limit']==2 and result['credited_ratio']==(.5 if kind in ('green','unknown') else 1)
    assert result['ratio']==1 and result['native_ratio_limit']==2


def test_all_posts_follow_date_lookup_without_browser(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    data=feed(download_from=None);data.pop('id');app.extensions['rss'].save(data)
    state=app.extensions['state'];state.save('b'*32,True);runtime=app.extensions['runtime']
    meta={'hashes':['c'*40],'name':'Linux'}
    runtime.rpc.side_effect=[{'token':'candidate','meta':meta},{'ok':True}]
    benefits=Mock()
    worker=rss_gate.RssGate(app.extensions['rss'],runtime,state,benefits);worker.tick()
    benefits.snapshot.assert_called_once_with(meta)
    assert runtime.rpc.call_args_list[-1].args[0]=='rss_resolve'
