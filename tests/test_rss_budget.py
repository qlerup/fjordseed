import json
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from app import create_app
from test_app import FakeRuntime, login
from test_rss_gate import gate, resolve
import rss
import rss_budget as budget
import rss_gate


def configure(root, limit=1000):
    (root/'fjord-rss-limit.json').write_text(json.dumps({'limit_bytes': limit}))


def measuring(monkeypatch, allocated=0, remaining=0):
    usage = {'allocated': allocated, 'remaining': remaining}
    def measure(api, roots, reservations):
        return (usage['allocated'], usage['remaining']+sum(v['size'] for v in reservations.values()), reservations)
    monkeypatch.setattr(budget, 'measure', measure)
    return usage


@pytest.mark.parametrize('value', [0, -1, True, False, '100', 1.5, 2**53, [], {}])
def test_bad_limits_rejected(value):
    with pytest.raises(ValueError):
        budget.validate({'limit_bytes': value})


def test_api_persists_gb_tb_clear_and_preserves_feeds(tmp_path):
    app=create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    c, headers=login(app)
    original=(tmp_path/'rss.json').read_text()
    assert c.post('/api/rss/storage-limit', json={'limit_bytes': 1024**4}).status_code==403
    for value in (1024**4, 750*1024**3, None):
        response=c.post('/api/rss/storage-limit', json={'limit_bytes': value}, headers=headers)
        assert response.status_code==200
        assert rss.Rss(tmp_path).storage_limit()['limit_bytes']==value
        assert c.get('/api/rss').json['storage_budget']['limit_bytes']==value
    assert (tmp_path/'rss.json').read_text()==original
    assert c.post('/api/rss/storage-limit', json={'limit_bytes': 0}, headers=headers).status_code==400


def test_disabled_never_queries_client_or_disk(tmp_path, monkeypatch):
    measure=Mock(side_effect=AssertionError('disabled budget measured'))
    monkeypatch.setattr(budget, 'measure', measure)
    api=Mock()
    assert budget.status(api, tmp_path)['paused'] is False
    api.assert_not_called();measure.assert_not_called()


def test_reserves_queue_and_unblocks_smaller_feeds_below_cap(tmp_path, monkeypatch):
    configure(tmp_path)
    usage=measuring(monkeypatch, allocated=800, remaining=200)
    first=budget.status(Mock(), tmp_path)
    assert first['paused'] and first['committed_bytes']==1000
    usage['remaining']=150
    assert budget.status(Mock(), tmp_path)['paused'] is False
    usage['remaining']=100
    assert budget.status(Mock(), tmp_path)['paused'] is False
    usage['remaining']=101
    assert budget.status(Mock(), tmp_path)['paused'] is False


def test_limit_changes_apply_immediately(tmp_path, monkeypatch):
    configure(tmp_path);measuring(monkeypatch, allocated=1000)
    assert budget.status(Mock(), tmp_path)['paused']
    configure(tmp_path, 1050)
    assert budget.status(Mock(), tmp_path)['paused'] is False
    configure(tmp_path, 900)
    assert budget.status(Mock(), tmp_path)['paused']


def test_measurement_failure_stops_only_new_rss(tmp_path, monkeypatch):
    configure(tmp_path)
    monkeypatch.setattr(budget, 'measure', Mock(side_effect=OSError('unavailable')))
    api=Mock()
    result=budget.status(api, tmp_path, candidate={'size':1, 'hashes':['a']}, reserve=True)
    assert result['paused'] and not result['fits'] and result['reason']=='measurement_error'
    api.assert_not_called()


def test_pending_add_survives_restart_and_prevents_cross_feed_overbooking(tmp_path, monkeypatch):
    configure(tmp_path);measuring(monkeypatch, allocated=700)
    def reserve(ident):
        with budget.admission_lock(tmp_path):
            return budget.status(Mock(), tmp_path, candidate={'size':200, 'hashes':[ident]}, reserve=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(reserve, ['a', 'b']))
    assert sum(r['fits'] for r in results)==1
    # New call reads durable state, without relying on an in-process cache.
    result=budget.status(Mock(), tmp_path)
    assert result['reserved_bytes']==200 and result['committed_bytes']==900


def test_measure_includes_manual_paused_buffers_and_reconciles_hybrid_hash(tmp_path, monkeypatch):
    root=tmp_path/'downloads';root.mkdir()
    monkeypatch.setattr(budget, 'temporary_usage', lambda roots: {'temporary_bytes': 500})
    api=Mock(return_value=Mock(json=lambda: [
        {'hash':'a', 'infohash_v2':'b', 'save_path':str(root/'.incomplete/a'), 'amount_left':200, 'state':'stoppedDL'},
        {'hash':'c', 'save_path':str(root/'permanent'), 'amount_left':900},
    ]))
    allocated,reserved,pending=budget.measure(api,[root],{'a':{'hashes':['a','b'],'size':400},'d':{'hashes':['d'],'size':100}})
    assert allocated==500 and reserved==300 and list(pending)==['d']
    assert api.call_args.args==('torrents/info',)


def test_unknown_live_metadata_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(budget,'temporary_usage',lambda roots:{'temporary_bytes':0})
    api=Mock(return_value=Mock(json=lambda:[{'save_path':str(tmp_path/'.incomplete/a'),'amount_left':0,'state':'metaDL'}]))
    with pytest.raises(ValueError):budget.measure(api,[tmp_path],{})


def candidate_sizes(monkeypatch, size):
    original=rss_gate.fetch_metadata
    def metadata(url):
        meta,payload=original(url)
        return {**meta, 'size':size},payload
    monkeypatch.setattr(rss_gate,'fetch_metadata',metadata)


def test_prepare_pauses_without_fetching_or_consuming_history(gate, monkeypatch):
    invoke,calls,fetched,articles,root,entry=gate
    configure(root);usage=measuring(monkeypatch, allocated=1000)
    result=invoke('rss_prepare')
    assert result['storage_paused'] and result['storage_assessment']['eligible']==2
    assert not fetched and not any(p=='torrents/add' for p,_ in calls)
    assert json.loads((root/('rss-history-'+entry['id']+'.json')).read_text())['storage_paused']
    usage['allocated']=890
    candidate_sizes(monkeypatch,100)
    assert invoke('rss_prepare')=={}  # Backlog is discarded on resumption.
    articles[-1]['date']=rss.datetime.now(rss.timezone.utc).isoformat()
    candidate=invoke('rss_prepare');resolve(invoke,candidate)
    assert len([p for p,_ in calls if p=='torrents/add'])==1


def test_advertised_sizes_skip_metadata_and_do_not_mark_read(gate, monkeypatch):
    invoke,calls,fetched,articles,root,entry=gate
    configure(root);measuring(monkeypatch,allocated=500)
    for article in articles:article['contentlength']='600'
    result=invoke('rss_prepare')
    assert result['storage_skipped']==2 and result['storage_paused']
    assert result['storage_assessment']['smallest_bytes']==600
    assert not fetched
    assert not any(p in ('torrents/add','rss/markAsRead') for p,_ in calls)


def test_metadata_rechecked_even_if_feed_understates_size(gate, monkeypatch):
    invoke,calls,_,articles,root,entry=gate
    configure(root);usage=measuring(monkeypatch,allocated=500)
    for article in articles:article['contentlength']='100'
    candidate_sizes(monkeypatch,600)
    candidate=invoke('rss_prepare')
    assert resolve(invoke,candidate)['storage_blocked']
    assert not any(p=='torrents/add' for p,_ in calls)
    history=json.loads((root/('rss-history-'+entry['id']+'.json')).read_text())
    assert candidate['token'] not in history['done']


def test_resolve_checks_space_again_without_starving_other_candidates(gate, monkeypatch):
    invoke,calls,_,_,root,entry=gate
    configure(root);usage=measuring(monkeypatch,allocated=700)
    candidate_sizes(monkeypatch,250)
    candidate=invoke('rss_prepare')
    usage['allocated']=950
    assert resolve(invoke,candidate)['storage_blocked']
    assert not any(p=='torrents/add' for p,_ in calls)
    assert not (root/('rss-pending-'+entry['id']+'.json')).exists()
    history=json.loads((root/('rss-history-'+entry['id']+'.json')).read_text())
    assert candidate['token'] not in history['done']
    usage['allocated']=700
    assert invoke('rss_prepare')=={}
    gate[3][-1]['date']=rss.datetime.now(rss.timezone.utc).isoformat()
    assert resolve(invoke,invoke('rss_prepare'))=={'ok':True}
    assert len([p for p,_ in calls if p=='torrents/add'])==1


def test_public_hides_reservations_and_marks_stale_status(tmp_path):
    qbit=tmp_path/'qbit';qbit.mkdir()
    data={'limit_bytes':1000,'paused':False,'checked_at':time.time(),'reservations':{'secret':{}}}
    (qbit/'rss-budget-state.json').write_text(json.dumps(data))
    assert 'reservations' not in budget.public(tmp_path, {'limit_bytes':1000})
    data['checked_at']-=36
    (qbit/'rss-budget-state.json').write_text(json.dumps(data))
    assert budget.public(tmp_path,{'limit_bytes':1000})['reason']=='pending'


def test_100_gb_guard_starts_at_inclusive_boundary(tmp_path, monkeypatch):
    gb=1024**3;configure(tmp_path,1000*gb)
    usage=measuring(monkeypatch,allocated=900*gb-1)
    assert budget.status(Mock(),tmp_path)['near_limit'] is False
    usage['allocated']+=1
    assert budget.status(Mock(),tmp_path)['near_limit'] is True


def test_one_feed_pauses_while_smaller_feed_continues_and_recovers(tmp_path, monkeypatch):
    from test_rss_gate import feed
    gb=1024**3;configure(tmp_path,1000*gb)
    usage=measuring(monkeypatch,allocated=950*gb)
    feeds=[feed(id='a'*32),feed(id='b'*32,name='Small feed',url='https://tracker.example/small')]
    (tmp_path/'fjord-rss.json').write_text(json.dumps(feeds))
    calls=[];fetched=[]
    def api(path,data=None,files=None):
        calls.append((path,data))
        if path=='rss/rules':
            payload={rss.PREFIX+f['id']:{'enabled':False,'mustContain':'','affectedFeeds':[f['url']]} for f in feeds}
        elif path.startswith('rss/items'):
            payload={rss.PREFIX+f['id']:{'url':f['url'],'articles':[
                {'id':f['id'],'title':f['name'],'date':'2026-10-08T12:00:00Z','torrentURL':f['url']+'/torrent','contentlength':str((60 if i==0 else 10)*gb)}
            ]} for i,f in enumerate(feeds)}
        else:payload=[]
        return Mock(json=lambda:payload,text='Ok.')
    def metadata(url):
        fetched.append(url)
        size=(60 if url.startswith(feeds[0]['url']+'/') else 10)*gb
        ident=('c' if size==60*gb else 'd')*40
        return {'size':size,'hashes':[ident],'name':'episode'}, {'magnet':'magnet:?xt=urn:btih:'+ident}
    monkeypatch.setattr(rss_gate,'fetch_metadata',metadata)
    def invoke(f,action='rss_prepare',**kwargs):
        return rss_gate.gate_rpc(action,{'feed_id':f['id'],'revision':rss_gate.fingerprint(f),**kwargs},api,tmp_path)
    result=invoke(feeds[0])
    assert result['storage_skipped']==1 and result['storage_paused']
    assert fetched==[]
    candidate=invoke(feeds[1])
    assert invoke(feeds[1],'rss_resolve',token=candidate['token'],hashes=candidate['meta']['hashes'],approved=True)=={'ok':True}
    assert len([p for p,_ in calls if p=='torrents/add'])==1
    # Capacity released by cleanup resumes the large feed automatically.
    usage['allocated']=920*gb
    assert invoke(feeds[0])=={}  # Only future publications can start after recovery.
    assert [f['enabled'] for f in json.loads((tmp_path/'fjord-rss.json').read_text())]==[True,True]


def test_full_budget_still_reads_this_feed_and_does_not_pause_empty_feed(gate,monkeypatch):
    invoke,calls,fetched,articles,root,entry=gate
    configure(root);measuring(monkeypatch,allocated=1100)
    for article in articles:article['contentlength']='60'
    result=invoke('rss_prepare')
    assert result['storage_assessment']=={
        'eligible':2,'fits':0,'unknown':0,'smallest_bytes':60,'available_bytes':0,'paused':True}
    assert any(p=='rss/items?withData=true' for p,_ in calls)
    assert not fetched
    message=rss_gate.feed_space_message(result['storage_assessment'])
    assert 'feedets 2 aktuelle poster' in message and 'Alle RSS-feeds' not in message
    for article in articles:article['isRead']=True
    assert invoke('rss_prepare')=={}


def test_api_does_not_replace_individual_feed_status_with_global_pause(tmp_path,monkeypatch):
    from test_rss_gate import feed
    gates=[]
    class Gate(rss_gate.RssGate):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);gates.append(self)
    monkeypatch.setattr('app.RssGate',Gate)
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    store=app.extensions['rss']
    ids=[]
    for i in range(2):
        data=feed(name='Feed '+str(i),url=f'https://tracker.example/rss/{i}');data.pop('id')
        ids.append(store.save(data))
    store.save_storage_limit({'limit_bytes':1000})
    (tmp_path/'qbit').mkdir(exist_ok=True)
    (tmp_path/'qbit/rss-budget-state.json').write_text(json.dumps({
        'limit_bytes':1000,'paused':True,'near_limit':True,'reason':'limit','checked_at':time.time()}))
    gates[0].storage_paused.add(ids[0]);gates[0].reports[ids[0]]='Dette feed har 2 for store poster.'
    gates[0].reports[ids[1]]='Afventer nye feedposter.'
    client,_=login(app)
    feeds=client.get('/api/rss').json['feeds']
    assert feeds[0]['status']=='storage_paused'
    assert feeds[0]['download_status']=='Dette feed har 2 for store poster.'
    assert feeds[1]['status']!='storage_paused'
    assert feeds[1]['download_status']=='Afventer nye feedposter.'


def test_auto_resume_boundary_survives_calls_and_rejects_pending(gate,monkeypatch):
    invoke,calls,fetched,articles,root,entry=gate
    now=rss.article_timestamp('2026-10-28T12:00:00Z')
    monkeypatch.setattr(rss_gate.time,'time',lambda:now)
    configure(root);usage=measuring(monkeypatch,allocated=700)
    candidate_sizes(monkeypatch,100)
    pending=invoke('rss_prepare')
    usage['allocated']=1000
    assert resolve(invoke,pending)['storage_blocked']
    usage['allocated']=0
    assert invoke('rss_prepare')=={}
    assert not (root/('rss-pending-'+entry['id']+'.json')).exists()
    history=json.loads((root/('rss-history-'+entry['id']+'.json')).read_text())
    assert history['resumed_after']==now and not history['storage_paused']
    # An item first discovered later still cannot be downloaded with an old date.
    articles[-1].update(id='late',date='2026-10-28T11:59:59Z')
    assert invoke('rss_prepare')=={}
    articles[-1]['date']=None
    assert invoke('rss_prepare')=={}
    articles[-1]['date']='2026-10-28T12:00:00Z'
    assert resolve(invoke,invoke('rss_prepare'))=={'ok':True}
    assert len([p for p,_ in calls if p=='torrents/add'])==1
