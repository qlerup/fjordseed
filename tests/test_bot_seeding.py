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
    rows += [dict(name='Waiting '+str(i),state='stalledUP',progress=1,upspeed=0) for i in range(501)]
    rows += [dict(name='Downloading',state='downloading',progress=.5),
             dict(name='Seeding',state='uploading',progress=1,upspeed=2048),
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


def test_seeding_requires_valid_positive_upload_speed_and_active_upload_state(tmp_path,monkeypatch):
    monkeypatch.setenv('FJORDHUB_URL','http://hub')
    monkeypatch.setenv('FJORDHUB_API_KEY','seed-test-secret')
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    rows=[dict(name='Active',state='uploading',upspeed=1024),
          dict(name='Forced active',state='forcedUP',upspeed=2048)]
    rows += [dict(name='Hidden',state=state,upspeed=speed) for state,speed in [
        ('stalledUP',0),('stalledUP',1024),('uploading',0),('forcedUP',0),
        ('uploading',None),('uploading',-1),('uploading',True),
        ('uploading',float('nan')),('uploading',float('inf')),
        ('pausedUP',1024),('stoppedUP',1024),('queuedUP',1024),('downloading',1024)]]
    app.extensions['runtime'].status=lambda:dict(torrents_available=True,torrents=rows)
    response=app.test_client().get('/api/hub/bot/seeding?activity=seeding',headers={'X-Hub-Key':'seed-test-secret'})
    assert response.status_code==200 and response.json['total']==2 and not response.json['more']
    assert [r['name'] for r in response.json['torrents']]==['Active','Forced active']
