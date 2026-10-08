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
                                        {'data':[row()]}])
    found=trackers.benefits.lookup((HASH,),'same name',trackers.entries())
    assert found['status']=='matched'
    assert found['matches'][0]['freeleech']==100
    assert found['matches'][0]['double_upload'] is True
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
