import json
from app import create_app
from green_credit import CreditLedger
import green_credit as credit
from rss_history import series_title,grouped
from test_app import FakeRuntime,login


def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(credit,'CONFIG',tmp_path/'qbit')
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    client,headers=login(app)
    def feed(name):
        return client.post('/api/rss',headers=headers,json=dict(name=name,url='https://tracker.example/'+name.replace(' ','_'),enabled=False,ratio_limit=2)).json['id']
    return app,client,headers,feed


def test_series_names_use_release_not_feed_label():
    for title in ['Politijagt.S01E02.DANiSH.1080p','Politijagt S02E01 720p','Politijagt.S01-S11.DANiSH']:
        assert series_title(title)=='Politijagt'
    assert series_title('Disney.Sjov.2026.10.23.NORDiC.1080p')=='Disney.Sjov'
    assert series_title('Nobody.2021.1080p.BluRay')=='Nobody.2021'
    groups=grouped([{'title':'The.Show.S01E01'},{'title':'The Show S02E02'},{'title':'Another.S01E01'}])
    assert len(groups)==2 and len(groups[1]['downloads'])==2
    assert groups[1]['exclude_title']=='The.Show'


def test_group_covers_use_archived_hash_and_local_cache(tmp_path, monkeypatch):
    app, client, headers, feed = setup(tmp_path, monkeypatch)
    ident = feed('TV')
    with CreditLedger().transaction() as ledger:
        ledger.record_rss_title(ident, 'a'*40, 'Show.S01E01')
    url = '/api/rss/'+ident+'/history/covers'
    calls = []
    poster = 'https://image.tmdb.org/t/p/w500/poster.jpg'
    def snapshot(meta):
        calls.append(meta)
        return {'status': 'ok', 'matches': [{'poster': poster}]}
    monkeypatch.setattr(app.extensions['trackers'].benefits, 'snapshot', snapshot)
    monkeypatch.setattr(app.extensions['covers'], 'request', lambda source: None)
    result = client.post(url, headers=headers, json={'groups': ['show', 'unrelated']})
    assert result.json == {'covers': {'show': {'url': None, 'pending': True}}}
    assert calls == [{'hashes': ['a'*40], 'name': 'Show.S01E01'}]
    monkeypatch.setattr(app.extensions['covers'], 'request', lambda source: '/api/covers/'+'b'*64)
    assert client.post(url, headers=headers, json={'groups': ['show']}).json['covers']['show'] == {
        'url': '/api/covers/'+'b'*64, 'pending': False}
    assert app.test_client().post(url, json={'groups': ['show']}).status_code in (400, 401, 403)
    assert client.post(url, json={'groups': ['show']}).status_code == 403
    assert client.post(url, headers=headers, json={'groups': ['show']*41}).status_code == 400
    assert client.post('/api/rss/missing/history/covers', headers=headers, json={'groups': ['show']}).status_code == 404
    monkeypatch.setattr(app.extensions['trackers'].benefits, 'snapshot', lambda meta: {
        'status': 'ok', 'matches': [{'poster': 'https://internal.example/private.jpg'}]})
    assert client.post(url, headers=headers, json={'groups': ['show']}).json['covers']['show'] == {'url': None, 'pending': False}


def test_existing_archive_and_sources_survive_deletion_and_restart(tmp_path,monkeypatch):
    app,client,h,feed=setup(tmp_path,monkeypatch)
    old=feed('Gammelt feed');new=feed('Dansk TV');other=feed('Alt TV')
    record={'title':'Politijagt.S01E02.DANiSH.1080p','added_at':10,'credited_uploaded':12345,'estimated':False}
    ledger={'_rss_upload':{'started_at':1,'feeds':{old:{'credited_uploaded':12345,'downloads':{'a'*40:record}}}}}
    (tmp_path/'qbit').mkdir(exist_ok=True);(tmp_path/'qbit/green-credit.json').write_text(json.dumps(ledger))
    assert client.post('/api/rss/'+new+'/history/sources',headers=h,json={'sources':[old]}).status_code==200
    data=client.get('/api/rss/'+new+'/history/groups').json
    assert data['count']==1 and data['groups'][0]['downloads'][0]['credited_uploaded']==12345
    assert data['groups'][0]['title']=='Politijagt'
    assert client.get('/api/rss/'+other+'/history/groups').json['count']==0
    assert client.get('/api/rss/'+old+'/history/groups').json['count']==1
    total=next(f for f in client.get('/api/rss').json['feeds'] if f['id']==new)
    assert total['credited_uploaded']==12345 and total['own_credited_uploaded']==0
    assert client.post('/api/rss/'+old+'/delete',headers=h).status_code==200
    restarted=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    c,_=login(restarted)
    assert c.get('/api/rss/'+new+'/history/groups').json==data
    assert c.get('/api/rss').json['credited_uploaded_total']==12345
    assert json.loads((tmp_path/'qbit/green-credit.json').read_text())==ledger


def test_exclusion_is_idempotent_scoped_and_uses_torrent_stem(tmp_path,monkeypatch):
    app,c,h,feed=setup(tmp_path,monkeypatch);ident=feed('Mit eget visningsnavn')
    with CreditLedger().transaction() as ledger:ledger.record_rss_title(ident,'a'*40,'The.Real.Show.S01E01.1080p')
    route='/api/rss/'+ident+'/history/exclude'
    assert c.post(route,json={'group':'the real show'}).status_code==403
    assert c.post(route,headers=h,json={'group':'fake'}).status_code==400
    for _ in range(2):assert c.post(route,headers=h,json={'group':'the real show'}).status_code==200
    saved=app.extensions['rss'].entries()[0]
    assert saved['title_exclude']==['The.Real.Show']
    assert saved['name']=='Mit eget visningsnavn'
    assert c.get('/api/rss/'+ident+'/history/groups').json['groups'][0]['excluded']
    assert app.test_client().get('/api/rss/'+ident+'/history/groups').status_code==401


def test_remove_exclusion_preserves_other_titles_and_feeds(tmp_path,monkeypatch):
    app,c,h,feed=setup(tmp_path,monkeypatch)
    ident=feed('TV');other=feed('Andet feed')
    store=app.extensions['rss']
    for key in (ident,other):
        current=next(f for f in store.entries() if f['id']==key)
        store.save({**current,'title_exclude':['THE Real Show','En anden serie']})
    with CreditLedger().transaction() as ledger:
        ledger.record_rss_title(ident,'a'*40,'The.Real.Show.S01E01.1080p')
    route='/api/rss/'+ident+'/history/exclude'
    assert c.post(route,json={'group':'the real show','excluded':False}).status_code==403
    assert c.post(route,headers=h,json={'group':'fake','excluded':False}).status_code==400
    assert c.post(route,headers=h,json={'group':'the real show','excluded':'false'}).status_code==400
    for _ in range(2):
        assert c.post(route,headers=h,json={'group':'the real show','excluded':False}).status_code==200
    assert next(f for f in store.entries() if f['id']==ident)['title_exclude']==['En anden serie']
    assert next(f for f in store.entries() if f['id']==other)['title_exclude']==['THE Real Show','En anden serie']
    group=c.get('/api/rss/'+ident+'/history/groups').json['groups'][0]
    assert not group['excluded'] and len(group['downloads'])==1
    assert c.post(route,headers=h,json={'group':'the real show'}).status_code==200
    assert c.get('/api/rss/'+ident+'/history/groups').json['groups'][0]['excluded']


def test_planned_danish_feed_imports_only_explicit_ids(tmp_path,monkeypatch):
    app,c,h,feed=setup(tmp_path,monkeypatch)
    old=feed('Politijagt');alt=feed('Alt TV')
    (tmp_path/'rss-history-presets.json').write_text(json.dumps([{'name':'Dansk TV','sources':[old]}]))
    assert c.post('/api/rss/'+old+'/delete',headers=h).status_code==200
    new=feed('Dansk TV')
    saved=next(f for f in app.extensions['rss'].entries() if f['id']==new)
    assert saved['history_sources']==[old] and alt not in saved['history_sources']
    assert c.post('/api/rss/'+new+'/history/sources',headers=h,json={'sources':[new]}).status_code==400
    assert c.post('/api/rss/'+new+'/history/sources',headers=h,json={'sources':['f'*32]}).status_code==400


def test_physical_history_and_download_credit_are_incremental(tmp_path,monkeypatch):
    monkeypatch.setattr(credit,'CONFIG',tmp_path)
    monkeypatch.setattr(credit,'POLICIES',tmp_path/'policy.json')
    ident='a'*40;feed='b'*32
    (tmp_path/'policy.json').write_text(json.dumps({ident:{'known':True,'until':None,'download_freeleech':50,'benefits_checked_at':100}}))
    row=dict(hash=ident,name='Politijagt.S01E01',tags='FjordSeed-RSS-'+feed,uploaded=20,downloaded=100,added_on=95,progress=.5)
    with CreditLedger().transaction() as ledger:
        ledger.update(row,now=100)
        ledger.update(dict(row,uploaded=40,downloaded=200,progress=1),now=110)
        ledger.update(dict(row,uploaded=30,downloaded=150),now=120)
        ledger.update(dict(row,uploaded=40,downloaded=160),now=130)
        item=ledger.entries['_rss_upload']['feeds'][feed]['downloads'][ident]
        assert item['uploaded']==50 and item['downloaded']==210
        assert item['credited_downloaded']==105
        assert not item.get('download_credit_incomplete')
    with CreditLedger().transaction() as ledger:
        ledger.update(dict(row,downloaded=170),now=1000)
        item=ledger.entries['_rss_upload']['feeds'][feed]['downloads'][ident]
        assert item['download_credit_incomplete']


def test_old_traffic_does_not_get_todays_freeleech_retroactively(tmp_path,monkeypatch):
    monkeypatch.setattr(credit,'CONFIG',tmp_path)
    monkeypatch.setattr(credit,'POLICIES',tmp_path/'policy.json')
    ident='a'*40;feed='b'*32
    (tmp_path/'policy.json').write_text(json.dumps({ident:{'known':True,'download_freeleech':100,'benefits_checked_at':100}}))
    with CreditLedger().transaction() as ledger:
        ledger.update(dict(hash=ident,tags='FjordSeed-RSS-'+feed,name='Show.S01',uploaded=100,downloaded=1000,added_on=1),now=100)
        item=ledger.entries['_rss_upload']['feeds'][feed]['downloads'][ident]
        assert item['download_credit_incomplete']
        assert 'credited_downloaded' not in item
