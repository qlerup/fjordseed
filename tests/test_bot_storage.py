from unittest.mock import Mock
from app import create_app
from storage import Storage
from test_app import FakeRuntime


def test_authenticated_projection_cache_and_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv('FJORDHUB_URL', 'http://hub')
    monkeypatch.setenv('FJORDHUB_API_KEY', 'secret')
    app=create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    app.extensions['runtime'].host_downloads='/mnt/media'
    measure=Mock(return_value={'temporary_bytes':4096,'rss_temporary_bytes':None,'current_rss_bytes':None})
    monkeypatch.setattr(Storage,'temporary_usage',measure)
    client=app.test_client()
    assert client.get('/api/hub/bot/storage').status_code==403
    assert client.get('/api/hub/bot/storage',headers={'X-Hub-Key':'wrong'}).status_code==403
    for _ in range(2):
        result=client.get('/api/hub/bot/storage',headers={'X-Hub-Key':'secret'})
        assert result.json=={'ok':True,'temporary_bytes':4096,'rss_temporary_bytes':None}
        assert result.headers['Cache-Control']=='no-store'
    assert measure.call_count==1
    app.extensions['runtime'].host_downloads='/mnt/other'
    measure.side_effect=ValueError('private path')
    result=client.get('/api/hub/bot/storage',headers={'X-Hub-Key':'secret'})
    assert result.status_code==503
    assert 'private' not in result.text
