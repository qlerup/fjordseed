import io
from concurrent.futures import ThreadPoolExecutor

from app import create_app
from manual_package import ManualPackage
from test_app import FakeRuntime, login


def torrent(name=b'fixture'):
    return b'd4:infod6:lengthi1e4:name'+str(len(name)).encode()+b':'+name+b'12:piece lengthi16384e6:pieces20:aaaaaaaaaaaaaaaaaaaaee'


def test_draft_persists_deduplicates_and_does_not_start_downloads(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    c,h=login(app)
    assert c.post('/api/manual-package',data={'torrent':(io.BytesIO(torrent()),'fixture.torrent')}).status_code==403
    assert c.post('/api/manual-package',headers=h,data={'url':'https://tracker.example/rss'}).status_code==400
    assert c.post('/api/manual-package',headers=h,data={'torrent':(io.BytesIO(b'invalid'),'bad.torrent')}).status_code==400
    result=c.post('/api/manual-package',headers=h,data={'torrent':(io.BytesIO(torrent()),'fixture.torrent')})
    assert result.status_code==200 and result.json['count']==1
    ident=result.json['items'][0]['id']
    assert set(result.json['items'][0])=={'id','name','size','created'}
    assert c.post('/api/manual-package',headers=h,data={'torrent':(io.BytesIO(torrent()),'copy.torrent')}).json['duplicate']
    app.extensions['runtime'].rpc.assert_not_called()
    restarted=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    c,h=login(restarted)
    assert c.get('/api/manual-package').json['count']==1
    assert c.get(f'/api/manual-package/{ident}/file').data==torrent()
    # VPN-offline start does not consume the draft.
    form={'package_item_id':ident,'ratio_action':'delete_time','seed_minutes':'60'}
    assert c.post('/api/torrents',headers=h,data=form).status_code==409
    assert c.get('/api/manual-package').json['count']==1
    restarted.extensions['state'].save('vpn',True)
    assert c.post('/api/torrents',headers=h,data={**form,'seed_minutes':'0'}).status_code==400
    assert c.post('/api/torrents',headers=h,data=form).status_code==200
    assert c.get('/api/manual-package').json['count']==0
    assert restarted.extensions['runtime'].rpc.call_args.args[1]['seed_minutes']==60
    # Repeating a successfully accepted package item cannot add it a second time.
    assert c.post('/api/torrents',headers=h,data=form).json['already_added'] is True
    restarted.extensions['runtime'].rpc.assert_called_once()


def test_package_is_scoped_to_owner_and_removal_only_affects_drafts(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    a,ha=login(app);b,hb=login(app)
    with a.session_transaction() as s:s['hub_uid']=1
    with b.session_transaction() as s:s['hub_uid']=2
    result=a.post('/api/manual-package',headers=ha,data={'torrent':(io.BytesIO(torrent()),'a.torrent')}).json
    ident=result['items'][0]['id']
    assert b.get('/api/manual-package').json['count']==0
    assert b.get(f'/api/manual-package/{ident}/file').status_code==404
    assert b.post('/api/torrents',headers=hb,data={'package_item_id':ident}).status_code==404
    assert b.post('/api/manual-package/remove',headers=hb,json={'ids':[ident]}).json['count']==0
    assert a.get('/api/manual-package').json['count']==1
    assert a.post('/api/manual-package/remove',headers=ha,json={'ids':['../escape']}).status_code==400
    assert a.post('/api/manual-package/remove',headers=ha,json={'ids':[ident]}).json['count']==0
    app.extensions['runtime'].rpc.assert_not_called()


def test_parallel_duplicate_staging_and_bounds(tmp_path,monkeypatch):
    from state import State
    store=ManualPackage(State(tmp_path))
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(lambda _:store.add('local',torrent(),'a.torrent'),range(10)))
    assert store.public('local')['count']==1
    assert sum(not r['duplicate'] for r in results)==1
    monkeypatch.setattr(store,'MAX_FILES',1)
    import pytest
    with pytest.raises(ValueError,match='fuld'):store.add('local',torrent(b'other'),'b.torrent')
    with pytest.raises(ValueError):store.add('local',torrent(),'feed.xml')
