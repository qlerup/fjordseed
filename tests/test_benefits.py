import io
import threading
from unittest.mock import Mock

from app import create_app
from test_app import FakeRuntime,login
from trackers import Trackers

HASH='a'*40
CONFIG={'provider':'nordicbytes','name':'NordicBytes','api_key':'fixture-not-real-key'}


def row(ident=HASH,**flags):
    return {'attributes':{'info_hash':ident,'freeleech':'100%','double_upload':True,**flags}}


def test_exact_hash_match_no_false_name_match_and_pagination(tmp_path):
    trackers=Trackers(tmp_path)
    trackers.save(CONFIG)
    trackers.read_json=Mock(side_effect=[{'data':[row('b'*40)],'meta':{'next_cursor':'cursor'}},
                                        {'data':[row(leechers=50)]}])
    found=trackers.benefits.lookup((HASH,),'same name',trackers.entries())
    assert found['status']=='matched'
    assert found['matches'][0]['freeleech']==100
    assert found['matches'][0]['double_upload'] is True
    assert found['matches'][0]['leechers']==50
    assert trackers.read_json.call_args.args[2]['cursor']=='cursor'
    assert 'download_link' not in str(found)
    trackers.read_json=Mock(return_value={'data':[row('b'*40)]})
    missing=trackers.benefits.lookup((HASH,),'same name',trackers.entries())
    assert missing['status']=='unknown' and not missing['matches']


def test_unavailable_flags_and_cache_survive_without_blocking_download(tmp_path):
    trackers=Trackers(tmp_path)
    trackers.save(CONFIG)
    trackers.read_json=Mock(side_effect=RuntimeError(CONFIG['api_key']))
    result=trackers.benefits.lookup((HASH,),'name',trackers.entries())
    assert result['status']=='unavailable'
    assert CONFIG['api_key'] not in str(result)
    assert trackers.benefits.flags({'freeleech':'nonsense','double_upload':'false'})['freeleech'] is None
    assert trackers.benefits.flags({'freeleech':'25%','double_upload':False})['freeleech']==25
    assert trackers.benefits.flags({'featured':True})['double_upload'] is True


def test_single_file_torrent_matches_tracker_release_without_media_extension(tmp_path):
    trackers=Trackers(tmp_path)
    trackers.save(CONFIG)
    release='Example.S02E02.1080p.WEB-DL.H.264-GROUP'
    def search(entry,url,params):
        return {'data':[row()] if params['name']==release else []}
    trackers.read_json=Mock(side_effect=search)
    result=trackers.benefits.lookup((HASH,),release+'.mkv',trackers.entries())
    assert result['status']=='matched'
    assert result['matches'][0]['freeleech']==100
    trackers.read_json.assert_called_once()
    assert trackers.read_json.call_args.args[2]['name']==release


def test_filename_normalization_never_accepts_a_different_hash(tmp_path):
    trackers=Trackers(tmp_path)
    trackers.save(CONFIG)
    trackers.read_json=Mock(return_value={'data':[row('b'*40)]})
    result=trackers.benefits.lookup((HASH,),'Example.Release.MKV',trackers.entries())
    assert result['status']=='unknown'
    assert not result['matches']
    assert trackers.read_json.call_args_list[0].args[2]['name']=='Example.Release'


def test_original_filename_search_is_preserved(tmp_path):
    trackers=Trackers(tmp_path)
    trackers.save(CONFIG)
    trackers.read_json=Mock(side_effect=[{'data':[]},{'data':[row()]}])
    assert trackers.benefits.lookup((HASH,),'Example.mkv',trackers.entries())['status']=='matched'
    assert trackers.read_json.call_args.args[2]['name']=='Example.mkv'


def test_internal_name_falls_back_to_title_and_verifies_hash(tmp_path):
    trackers=Trackers(tmp_path)
    trackers.save(CONFIG)
    name='Marshals (2026) S01 (1080p BluRay x265 10bit EAC3 5.1 Ghost)'
    def search(entry,url,params):
        return {'data':[row('b'*40),row(created_at='2026-10-23T12:00:00Z')]
                if params['name']=='Marshals' else []}
    trackers.read_json=Mock(side_effect=search)
    result=trackers.benefits.lookup((HASH,),name,trackers.entries())
    assert result['status']=='matched'
    assert result['matches'][0]['created_at']=='2026-10-23T12:00:00Z'
    assert trackers.read_json.call_args.args[2]['name']=='Marshals'
    trackers.read_json=Mock(return_value={'data':[row('b'*40)]})
    assert trackers.benefits.lookup((HASH,),name,trackers.entries())['status']=='unknown'


def test_async_cache_deduplicates_and_invalidates_credentials(tmp_path):
    trackers=Trackers(tmp_path)
    ident=trackers.save(CONFIG)
    benefits=trackers.benefits
    meta={'hashes':[HASH],'name':'name'}
    assert benefits.request(meta)['status']=='pending'
    assert benefits.request(meta)['status']=='pending'
    assert benefits.jobs.qsize()==1
    trackers.save({**CONFIG,'id':ident,'api_key':'replacement-fixture-key'})
    assert benefits.request(meta)['status']=='pending'
    assert benefits.jobs.qsize()==2
    trackers.remove(ident)
    assert benefits.request(meta)['status']=='unknown'


def test_modal_lookup_takes_priority_and_worker_caches_result(tmp_path):
    trackers=Trackers(tmp_path)
    trackers.save(CONFIG)
    benefits=trackers.benefits
    meta={'hashes':[HASH],'name':'name'}
    benefits.request(meta,priority=1)
    benefits.request(meta,priority=0)
    assert benefits.jobs.queue[0][0]==0
    stop=threading.Event()
    def lookup(*args):
        stop.set()
        return {'status':'matched','matches':[{'freeleech':100}]}
    benefits.lookup=Mock(side_effect=lookup)
    benefits.run(stop)
    assert benefits.request(meta)['status']=='matched'
    benefits.lookup.assert_called_once()


def test_preview_overtakes_periodic_accounting_backlog(tmp_path):
    trackers=Trackers(tmp_path)
    trackers.save(CONFIG)
    benefits=trackers.benefits
    for i in range(170):
        benefits.accounting_poll({'hashes':[f'{i:040x}'],'name':f'Background {i}'})
    # Background work leaves capacity available for interactive requests.
    assert benefits.jobs.qsize()==150
    meta={'hashes':['f'*40],'name':'New manual download'}
    assert benefits.request(meta)['status']=='pending'
    stop=threading.Event()
    def lookup(hashes,name,entries):
        assert name==meta['name']
        stop.set()
        return {'status':'matched','matches':[]}
    benefits.lookup=Mock(side_effect=lookup)
    benefits.run(stop)
    benefits.lookup.assert_called_once()
    assert benefits.request(meta)['status']=='matched'


def test_worker_keeps_http_spacing_without_extra_job_delay(tmp_path,monkeypatch):
    trackers=Trackers(tmp_path);trackers.save(CONFIG)
    benefits=trackers.benefits
    clock=[100.0];starts=[]
    class Stop:
        stopped=False
        def is_set(self):return self.stopped
        def wait(self,seconds):
            clock[0]+=seconds
            return self.stopped
    stop=Stop()
    monkeypatch.setattr('benefits.time.monotonic',lambda:clock[0])
    def read(entry,url,params):
        starts.append(clock[0]);clock[0]+=.2
        if len(starts)==2:stop.stopped=True
        return {'data':[row(HASH if params['name']=='First' else 'b'*40)]}
    trackers.read_json=read
    benefits.request({'hashes':[HASH],'name':'First'})
    benefits.request({'hashes':['b'*40],'name':'Second'})
    benefits.run(stop)
    assert starts==[100.0,101.0]


def test_rss_leechers_can_refresh_before_normal_benefits_cache_expires(tmp_path):
    import time
    trackers=Trackers(tmp_path);trackers.save(CONFIG)
    benefits=trackers.benefits;meta={'hashes':[HASH],'name':'name'}
    benefits.request(meta)
    cached=next(iter(benefits.cache.values()))
    cached.update(at=time.time()-31,result={'status':'matched','matches':[{'leechers':50}]})
    assert benefits.request(meta)['status']=='matched'
    assert benefits.request(meta,max_age=30)['status']=='pending'


def test_preview_is_authenticated_and_passkeys_never_forwarded(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    assert app.test_client().post('/api/torrents/preview').status_code==403
    client,headers=login(app)
    benefits=app.extensions['trackers'].benefits
    benefits.request=Mock(return_value={'status':'unknown','message':'Unknown'})
    raw=b'd8:announce28:https://example/passkey-test4:infod4:name11:example.iso6:lengthi4eee'
    result=client.post('/api/torrents/preview',headers=headers,data={'torrent':(io.BytesIO(raw),'file.torrent')})
    assert result.status_code==200
    assert 'passkey' not in str(benefits.request.call_args)
    app.extensions['runtime'].rpc.assert_not_called()
    assert client.post('/api/torrents/preview',headers=headers,data={'torrent':(io.BytesIO(b'broken'),'file.torrent')}).status_code==400
