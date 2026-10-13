import json

import pytest
from app import create_app
from test_app import FakeRuntime, login
from test_rss_gate import feed
import rss


@pytest.mark.parametrize('title,include,exclude,expected',[
    ('Politijagt.S01E02',[],['politijagt'],False),
    ('Badehotellet.S10E01',[],['Politijagt'],True),
    ('POLITIJAGT_S01E02',['Politijagt'],[],True),
    ('Den.store-bagedyst.S01',['Den store bagedyst'],[],True),
    ('Badehotellet',['Politijagt','Badehotellet'],[],True),
    ('Badehotellet',['Politijagt'],[],False),
    ('Politijagt',['Politijagt'],['Politijagt'],False),
    ('Æbleøen',['æbleøen'],[],True),
    ('<img src=x> Politijagt',[],['Politijagt'],False),
    (None,[],[],True),
    (None,[],['Politijagt'],False),
    ('', ['Politijagt'],[],False),
])
def test_plain_title_matching(title,include,exclude,expected):
    assert rss.title_matches({'title':title},feed(title_include=include,title_exclude=exclude)) is expected


@pytest.mark.parametrize('field',['title_include','title_exclude'])
@pytest.mark.parametrize('value',[None,'Politijagt',{},[True],[''],['...'],['x'*121],['bad\ntitle'],['title']*51])
def test_invalid_title_lists_rejected(field,value):
    with pytest.raises(ValueError):rss.validate_feed(feed(**{field:value}))


def test_normalize_duplicates_and_migrate_without_restoring_legacy_filters(tmp_path):
    entry=feed(title_include=[' Politijagt ','POLITIJAGT'],title_exclude=['Den.store.bagedyst','den store bagedyst'])
    entry.update(include='old regex',max_size_gb=2)
    (tmp_path/'rss.json').write_text(json.dumps([entry]))
    store=rss.Rss(tmp_path)
    saved=store.entries()[0]
    assert saved['title_include']==['Politijagt']
    assert saved['title_exclude']==['Den.store.bagedyst']
    assert 'include' not in saved and 'max_size_gb' not in saved
    assert rss.Rss(tmp_path).entries()==store.entries()


def test_api_filter_roundtrip_edit_and_toggle_preserve_lists(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    client,headers=login(app)
    data=feed(title_include=[],title_exclude=['Politijagt']);data.pop('id')
    saved=client.post('/api/rss',headers=headers,json=data)
    assert saved.status_code==200
    ident=saved.json['id']
    assert client.get('/api/rss').json['feeds'][0]['title_exclude']==['Politijagt']
    assert client.post('/api/rss/'+ident+'/enabled',headers=headers,json={'enabled':False}).status_code==200
    assert app.extensions['rss'].entries()[0]['title_exclude']==['Politijagt']
    assert client.post('/api/rss',headers=headers,json={'id':ident,'name':'Updated'}).status_code==200
    assert app.extensions['rss'].entries()[0]['title_exclude']==['Politijagt']
    assert client.post('/api/rss',headers=headers,json={'id':ident,'title_exclude':[]}).status_code==200
    assert rss.Rss(tmp_path).entries()[0]['title_exclude']==[]
