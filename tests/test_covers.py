import hashlib
import base64
import json
import os
import time
from unittest.mock import Mock

import pytest

from app import create_app
from covers import Covers, poster_url
from test_app import FakeRuntime, login
from trackers import Trackers

URL='https://tmdbc.org/tmdb/t/p/w92/fixture.jpg'


@pytest.mark.parametrize('url',['http://tmdbc.org/tmdb/t/p/w92/x.jpg','https://127.0.0.1/x.jpg',
    'https://tmdbc.org.evil.test/tmdb/t/p/w92/x.jpg','https://user@tmdbc.org/tmdb/t/p/w92/x.jpg',
    URL+'?key=secret','https://tmdbc.org/tmdb/t/p/w92/../../x.jpg',URL.replace('.jpg','.svg')])
def test_rejects_nonpublic_or_credentialed_sources(url):
    assert poster_url(url) is None


def test_async_download_is_deduplicated_and_served_only_after_login(tmp_path,monkeypatch):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    covers=app.extensions['covers'];ident=hashlib.sha256(URL.encode()).hexdigest()
    assert covers.request(URL) is None
    assert covers.request(URL) is None
    assert covers.jobs.qsize()==1
    image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
    response=Mock(status_code=200)
    response.iter_content.return_value=[image]
    response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    client=Mock();client.get.return_value=response
    client.__enter__=Mock(return_value=client);client.__exit__=Mock(return_value=False)
    monkeypatch.setattr('covers.requests.Session',lambda:client)
    covers.download(ident,URL)
    assert covers.request(URL)=='/api/covers/'+ident
    assert 'headers' not in client.get.call_args.kwargs
    assert client.get.call_args.kwargs['allow_redirects'] is False
    assert client.trust_env is False
    assert app.test_client().get('/api/covers/'+ident).status_code==401
    browser,_=login(app)
    result=browser.get('/api/covers/'+ident)
    assert result.status_code==200 and result.mimetype=='image/png'
    assert result.headers['Cache-Control']=='private, max-age=3600'
    assert browser.get('/api/covers/not-a-hash').status_code==404
    os.utime(covers.path(ident),(time.time()-2*covers.TTL,)*2)
    covers.jobs.get_nowait();covers.pending.clear()
    assert covers.request(URL)=='/api/covers/'+ident
    assert covers.jobs.qsize()==1


def test_old_snapshots_get_cover_without_rewriting_green_policy(tmp_path):
    trackers=Trackers(tmp_path)
    ident=trackers.save({'provider':'nordicbytes','name':'Fixture','api_key':'fixture-not-real-key'})
    meta={'hashes':['a'*40],'name':'Release'}
    old={'status':'matched','matches':[{'tracker_id':ident,'tracker_provider':'nordicbytes',
        'created_at':'2023-11-14T22:13:20Z','freeleech':100}]}
    trackers.benefits.remember(meta,old)
    before=json.loads((tmp_path/'rpc'/'green-policy.json').read_text())
    fresh={'status':'matched','matches':[{**old['matches'][0],'poster':URL,'freeleech':0,'created_at':None}]}
    trackers.benefits.request=Mock(return_value=fresh)
    updated=trackers.benefits.snapshot(meta)
    assert updated['matches'][0]['poster']==URL
    assert updated['matches'][0]['freeleech']==100
    assert updated['matches'][0]['created_at']==old['matches'][0]['created_at']
    assert json.loads((tmp_path/'rpc'/'green-policy.json').read_text())==before
    trackers.benefits.snapshot(meta)
    trackers.benefits.request.assert_called_once()


def test_cache_has_size_and_age_limits(tmp_path):
    cache=Covers(tmp_path);cache.MAX_CACHE=10
    for i in range(3):
        path=cache.root/(str(i)*64+'.img');path.write_bytes(b'x'*8)
        os.utime(path,(time.time()-i,)*2)
    cache.prune()
    assert sum(p.stat().st_size for p in cache.root.glob('*.img'))<=10
    path=next(cache.root.glob('*.img'))
    os.utime(path,(time.time()-8*cache.TTL,)*2);cache.prune()
    assert not list(cache.root.glob('*.img'))


@pytest.mark.parametrize('status,raw',[(302,b'\xff\xd8\xff'),(200,b'<svg></svg>'),(200,b'\xff\xd8\xff'+b'x'*100)])
def test_redirects_nonimages_and_oversized_images_are_not_cached(tmp_path,monkeypatch,status,raw):
    cache=Covers(tmp_path);cache.MAX_IMAGE=50
    response=Mock(status_code=status);response.iter_content.return_value=[raw]
    response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    client=Mock();client.get.return_value=response
    client.__enter__=Mock(return_value=client);client.__exit__=Mock(return_value=False)
    monkeypatch.setattr('covers.requests.Session',lambda:client)
    with pytest.raises(ValueError):cache.download('a'*64,URL)
    assert not list(cache.root.glob('*.img'))


def test_cover_requires_exact_tracker_hash_match(tmp_path):
    trackers=Trackers(tmp_path)
    trackers.save({'provider':'nordicbytes','name':'Fixture','api_key':'fixture-not-real-key'})
    trackers.read_json=Mock(return_value={'data':[{'attributes':{'info_hash':'a'*40,'meta':{'poster':URL}}}]})
    found=trackers.benefits.lookup(('a'*40,),'Release',trackers.entries())
    assert found['matches'][0]['poster']==URL
    assert not trackers.benefits.lookup(('b'*40,),'Release',trackers.entries())['matches']
