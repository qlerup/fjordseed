import io
from unittest.mock import Mock

import pytest

from app import create_app
from hub import HubError


class FakeRuntime:
    def __init__(self, state):
        self.state = state
        self.rpc = Mock(return_value={'ok':True})
    def configure(self, data):
        if not isinstance(data, dict) or type(data.get('enabled')) is not bool:
            raise ValueError('Ugyldige indstillinger')
        self.state.save(data.get('profile_id',''), data['enabled'])
    def status(self):
        return dict(self.state.get(), ready=False, message='Venter på VPN.', profiles=[],
                    torrents=[], transfer={}, download_path='/downloads')


def login(app):
    c = app.test_client()
    c.get('/login')
    with c.session_transaction() as s:
        csrf = s['csrf']
    password = (app.extensions['state'].root/'initial-login.txt').read_text().strip()
    assert c.post('/login',data={'username':'admin','password':password,'csrf':csrf}).status_code == 302
    with c.session_transaction() as s:
        csrf = s['csrf']
    return c, {'X-CSRF-Token':csrf}


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)


def test_auth_csrf_host_and_stopped_gate(app):
    c = app.test_client()
    assert c.get('/api/status').status_code == 401
    assert c.get('/healthz',headers={'Host':'evil.example'}).status_code == 403
    c, h = login(app)
    assert c.post('/api/settings',json={}).status_code == 403
    assert c.post('/api/settings',headers=h,json=[]).status_code == 400
    assert c.post('/api/torrents',headers=h,data={'magnet':'magnet:?xt=urn:btih:'+'a'*40}).status_code == 409
    app.extensions['runtime'].rpc.assert_not_called()


def test_add_and_actions_are_allowlisted(app):
    c,h=login(app)
    app.extensions['state'].save('a'*32, True)
    for value in ('https://tracker.example/a.torrent','file:///etc/passwd','magnet:?a\nhttp://x'):
        assert c.post('/api/torrents',headers=h,data={'magnet':value}).status_code == 400
    assert c.post('/api/torrents',headers=h,data={'magnet':'magnet:?xt=urn:btih:'+'a'*40}).status_code == 200
    assert c.post('/api/torrents',headers=h,data={'torrent':(io.BytesIO(b'd4:infodee'),'a.torrent')}).status_code == 200
    assert c.post('/api/torrents',headers=h,data={'torrent':(io.BytesIO(b'bad'),'a.torrent')}).status_code == 400
    for action in ('start','stop','delete'):
        assert c.post('/api/torrents/'+'a'*40+'/'+action,headers=h).status_code == 200
    assert c.post('/api/torrents/'+'a'*40+'/setPreferences',headers=h).status_code == 400


def test_hub_sso_revoke_and_outage(tmp_path, monkeypatch):
    monkeypatch.setenv('FJORDHUB_URL','http://hub')
    monkeypatch.setenv('FJORDHUB_API_KEY','fixture-key')
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    hub=app.extensions['hub']
    user={'id':1,'role':'admin','must_change_password':False}
    hub.call=Mock(side_effect=[dict(user,ok=True),{'ok':True,'items':[user]}])
    c=app.test_client()
    assert c.get('/hub-login?token=test').status_code==302
    assert c.get('/api/status').status_code==200
    hub.expires=0
    hub.call=Mock(side_effect=HubError('Unavailable',503))
    assert c.get('/api/status').status_code==503
    hub.call=Mock(return_value={'ok':True,'items':[]})
    assert c.get('/api/status').status_code==401
    assert c.get('/api/status').status_code==401
    assert not (tmp_path/'initial-login.txt').exists()


def test_nonadmin_cannot_control_seedbox(tmp_path,monkeypatch):
    monkeypatch.setenv('FJORDHUB_URL','http://hub')
    monkeypatch.setenv('FJORDHUB_API_KEY','fixture-key')
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    app.extensions['hub'].call=Mock(return_value={'ok':True,'id':1,'role':'user'})
    assert app.test_client().get('/hub-login?token=test').status_code==403
