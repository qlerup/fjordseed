import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import rss
from test_app import FakeRuntime, login
from app import create_app


def feed(**changes):
    return dict(name='Linux releases',url='https://tracker.example/rss?passkey=fixture',
        folder='linux/releases',enabled=False,include='Linux',ratio_limit=2,ratio_action='keep',**changes)


@pytest.mark.parametrize('field,value', [('folder','../escape'),('folder','/absolute'),
    ('folder','a/../../escape'),('url','http://127.0.0.1/rss'),('url','file:///etc/passwd'),
    ('url','https://user:password@tracker.example/rss'),('ratio_limit',-1),('ratio_limit','nan'),
    ('ratio_action','invalid'),('enabled','yes')])
def test_reject_invalid_rule(field,value):
    data=feed();data[field]=value
    with pytest.raises(ValueError):rss.validate_feed(data)


def test_private_url_preserved_and_removal_keeps_files(tmp_path):
    downloads=tmp_path/'downloads';downloads.mkdir()
    fixture=downloads/'keep.bin';fixture.write_bytes(b'keep')
    store=rss.Rss(tmp_path,downloads)
    ident=store.save(feed())
    public=store.public()
    assert 'fixture' not in json.dumps(public) and 'url' not in public['feeds'][0]
    edited=feed();edited.update(id=ident,url='',name='Updated')
    store.save(edited)
    assert store.entries()[0]['url']==feed()['url']
    store.remove(ident)
    assert fixture.read_bytes()==b'keep' and store.entries()==[]


def test_native_rule_has_folder_tag_policy_and_preserves_history(tmp_path,monkeypatch):
    ident='a'*32;name=rss.PREFIX+ident;calls=[]
    monkeypatch.setattr(rss,'folder_path',lambda folder:tmp_path/folder)
    def api(path,data=None):
        calls.append((path,data))
        return Mock(json=lambda: {name:{'previouslyMatchedEpisodes':['old']}} if path=='rss/rules' else {})
    entry=feed();entry.update(id=ident,enabled=True,ratio_action='delete')
    rss.sync_rss([entry],api)
    prefs=[json.loads(data['json']) for path,data in calls if path=='app/setPreferences']
    assert prefs[0]['rss_auto_downloading_enabled'] is False
    assert prefs[-1]['rss_auto_downloading_enabled'] is True
    rule=json.loads(next(data['ruleDef'] for path,data in calls if path=='rss/setRule'))
    params=rule['torrentParams']
    assert params['force_start'] is False
    assert params['ratio_limit']==2 and params['share_limit_action']=='RemoveWithContent'
    assert params['save_path']==str(tmp_path/'linux/releases')
    assert params['tags']==['FjordSeed-RSS-'+ident] and params['use_auto_tmm'] is False
    assert rule['previouslyMatchedEpisodes']==['old'] and rule['affectedFeeds']==[entry['url']]


def test_api_auth_and_separate_origin_even_after_feed_removed(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    client,headers=login(app)
    assert client.post('/api/rss',json=feed()).status_code==403
    assert client.post('/api/rss',headers=headers,json=feed()).status_code==200
    public=client.get('/api/rss').json
    assert 'passkey' not in json.dumps(public)
    ident=public['feeds'][0]['id']
    runtime=app.extensions['runtime']
    runtime.status=lambda: {'torrents':[{'hash':'b'*40,'name':'Manual'},
        {'hash':'c'*40,'name':'Automatic','tags':'other,FjordSeed-RSS-'+ident}]}
    app.extensions['trackers'].benefits.request=lambda *args,**kwargs: {'status':'unknown'}
    rows=client.get('/api/status').json['torrents']
    assert rows[0]['rss_feed'] is None and rows[1]['rss_feed']=='Linux releases'
    assert client.post('/api/rss/'+ident+'/delete',headers=headers).status_code==200
    assert client.get('/api/status').json['torrents'][1]['rss_feed']=='RSS-feed (fjernet)'
