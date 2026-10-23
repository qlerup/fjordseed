from app import create_app
from test_app import FakeRuntime


def test_bot_endpoint_requires_app_key_even_with_browser_session(tmp_path, monkeypatch):
    monkeypatch.setenv('FJORDHUB_URL', 'http://hub')
    monkeypatch.setenv('FJORDHUB_API_KEY', 'seed-test-secret')
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    client = app.test_client()
    runtime = app.extensions['runtime']
    runtime.status = lambda: dict(torrents_available=True, torrents=[dict(
        name='Test ISO', state='uploading', progress=1, ratio=.4,
        credited_ratio=.2, seeding_time=3600, download_path='/private',
        tracker='https://private?passkey=secret', hash='a'*40)])
    assert client.get('/api/hub/bot/seeding').status_code == 403
    with client.session_transaction() as session:
        session['authenticated'] = True
    assert client.get('/api/hub/bot/seeding', headers={'X-Hub-Key':'wrong'}).status_code == 403
    response = client.get('/api/hub/bot/seeding', headers={'X-Hub-Key':'seed-test-secret'})
    assert response.status_code == 200
    assert response.json['torrents'] == [dict(name='Test ISO', state='uploading', progress=1,
                                             ratio=.4, seeding_time=3600)]
    assert response.headers['Cache-Control'] == 'no-store'
    runtime.status = lambda: dict(torrents_available=False, torrents=[])
    assert client.get('/api/hub/bot/seeding', headers={'X-Hub-Key':'seed-test-secret'}).status_code == 503


def test_standalone_does_not_expose_bot_data(tmp_path, monkeypatch):
    monkeypatch.delenv('FJORDHUB_URL', raising=False)
    monkeypatch.delenv('FJORDHUB_API_KEY', raising=False)
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    assert app.test_client().get('/api/hub/bot/seeding').status_code == 403


def test_activity_filtering_happens_before_list_limit(tmp_path, monkeypatch):
    monkeypatch.setenv('FJORDHUB_URL', 'http://hub')
    monkeypatch.setenv('FJORDHUB_API_KEY', 'seed-test-secret')
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    rows = [dict(name='Paused '+str(i),state='pausedDL',progress=.2) for i in range(501)]
    rows += [dict(name='Downloading',state='downloading',progress=.5),
             dict(name='Seeding',state='stalledUP',progress=1),
             dict(name='Queued',state='queuedDL',progress=.1),
             dict(name='Stopped seed',state='stoppedUP',progress=1)]
    app.extensions['runtime'].status=lambda:dict(torrents_available=True,torrents=rows)
    client=app.test_client(); headers={'X-Hub-Key':'seed-test-secret'}
    response=client.get('/api/hub/bot/seeding?activity=downloading',headers=headers)
    assert response.status_code==200 and response.json['total']==1 and not response.json['more']
    assert [row['name'] for row in response.json['torrents']]==['Downloading']
    response=client.get('/api/hub/bot/seeding?activity=seeding',headers=headers)
    assert [row['name'] for row in response.json['torrents']]==['Seeding']
    assert client.get('/api/hub/bot/seeding?activity=bad',headers=headers).status_code==400
