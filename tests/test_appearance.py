from app import create_app
from test_app import FakeRuntime, login
import pytest


@pytest.mark.parametrize('theme', ['fjord', 'viking', 'nordic'])
def test_theme_persists_without_changing_seedbox(tmp_path, theme):
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    c, h = login(app)
    state = app.extensions['state']
    state.save('vpn-original', True)
    assert c.get('/api/appearance').json == {'theme': 'fjord', 'animation': True}
    assert c.post('/api/appearance', json={'theme': 'viking', 'animation': True}).status_code == 403
    for value in ([], {}, {'theme': 'unknown', 'animation': True}, {'theme': 'viking', 'animation': 'false'}):
        assert c.post('/api/appearance', headers=h, json=value).status_code == 400
    assert c.post('/api/appearance', headers=h, json={'theme': theme, 'animation': False}).status_code == 200
    state.save('vpn-original', False)
    assert state.get()['profile_id'] == 'vpn-original'
    assert state.get()['enabled'] is False
    app.extensions['runtime'].rpc.assert_not_called()
    restarted = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    c, _ = login(restarted)
    assert c.get('/api/appearance').json == {'theme': theme, 'animation': False}
    assert f'data-theme="{theme}" data-animation="false"'.encode() in c.get('/').data
