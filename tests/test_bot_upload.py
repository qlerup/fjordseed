from unittest.mock import Mock

from bot_upload import upload_choices
from app import create_app
from test_app import FakeRuntime


def test_choices_keep_feed_credit_and_account_upload_separate_and_drop_secrets():
    rss = Mock()
    rss.public.return_value = {'feeds': [dict(id='feed1', name='Film', credited_uploaded=2048,
        credit_estimated=True, url='secret', credited_ratio=99)]}
    trackers = Mock()
    trackers.public.return_value = {'trackers': [dict(id='t1', name='Tracker', status='ok',
        updated_at=1000, stats={'uploaded':8192}, api_key='secret', username='private')]}
    result = upload_choices(rss,trackers,now=1100)
    assert result == {'ok':True,'options':[
        dict(kind='rss',id='feed1',name='Film',credited_uploaded=2048,estimated=True,updated_at=None),
        dict(kind='tracker',id='t1',name='Tracker',credited_uploaded=8192,estimated=False,updated_at=1000)]}
    assert 'secret' not in str(result) and 'private' not in str(result)


def test_stale_unavailable_and_invalid_amounts_are_not_reported_as_zero():
    rss,trackers=Mock(),Mock()
    rss.public.return_value={'feeds':[dict(id='f',name='RSS',credited_uploaded=float('nan'))]}
    for status,updated,amount in [('ok',100,42),('error',1000,42),('ok',1000,-1),('ok',1000,True)]:
        trackers.public.return_value={'trackers':[dict(id='t',name='Tracker',status=status,
            updated_at=updated,stats={'uploaded':amount})]}
        result=upload_choices(rss,trackers,now=1100)
        assert all(o['credited_uploaded'] is None for o in result['options'])


def test_upload_endpoint_requires_hub_app_key_and_returns_only_projection(tmp_path,monkeypatch):
    monkeypatch.setenv('FJORDHUB_URL','http://hub')
    monkeypatch.setenv('FJORDHUB_API_KEY','upload-secret')
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    app.extensions['rss'].public=lambda:{'feeds':[dict(id='f',name='Film',credited_uploaded=1234,url='private')]}
    app.extensions['trackers'].public=lambda:{'trackers':[]}
    client=app.test_client()
    url='/api/hub/bot/upload'
    assert client.get(url).status_code==403
    with client.session_transaction() as session:session['authenticated']=True
    assert client.get(url,headers={'X-Hub-Key':'wrong'}).status_code==403
    response=client.get(url,headers={'X-Hub-Key':'upload-secret'})
    assert response.status_code==200
    assert response.json['options'][0]['credited_uploaded']==1234
    assert 'private' not in response.get_data(as_text=True)
    assert response.headers['Cache-Control']=='no-store'
