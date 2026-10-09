from unittest.mock import Mock
import pytest
from app import create_app
from test_app import FakeRuntime, login
from qbit_rpc import execute


@pytest.mark.parametrize('value', [1, 2, 5, 2.5])
def test_edit_ratio_preserves_action_and_time_without_restart(monkeypatch, value):
    calls = []
    row = {'hash': 'a' * 40, 'share_limit_action': 'RemoveWithContent', 'state': 'stoppedUP'}
    def api(path, data=None):
        calls.append((path, data))
        return Mock(json=lambda: {'current_network_interface': 'tun0', 'upnp': False} if path == 'app/preferences' else [row])
    monkeypatch.setattr('qbit_rpc.call', api)
    assert execute('ratio', {'hash': row['hash'], 'ratio_limit': value}) == {'ok': True}
    assert calls[-1] == ('torrents/setShareLimits', {'hashes': row['hash'], 'ratioLimit': value,
        'seedingTimeLimit': 2880, 'inactiveSeedingTimeLimit': -1, 'shareLimitAction': 'RemoveWithContent'})
    assert not any(path in ('torrents/start', 'torrents/stop', 'torrents/add') for path, _ in calls)


@pytest.mark.parametrize('value', [None, True, 0, -1, 0.5, 10001, 'nan', 'inf'])
def test_invalid_ratio_rejected_before_changing_client(monkeypatch, value):
    call = Mock(return_value=Mock(json=lambda: {'current_network_interface': 'tun0', 'upnp': False}))
    monkeypatch.setattr('qbit_rpc.call', call)
    with pytest.raises(ValueError):
        execute('ratio', {'hash': 'a' * 40, 'ratio_limit': value})
    assert call.call_count == 1


def test_ratio_route_validates_and_uses_existing_auth_and_vpn_gate(tmp_path):
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    client, headers = login(app)
    url = '/api/torrents/' + 'a' * 40 + '/ratio'
    assert client.post(url, json={'ratio_limit': 5}).status_code == 403
    assert client.post(url, headers=headers, json={'ratio_limit': 5}).status_code == 409
    app.extensions['state'].save('b' * 32, True)
    for value in (True, None, 0, -1, 10001):
        assert client.post(url, headers=headers, json={'ratio_limit': value}).status_code == 400
    assert client.post(url, headers=headers, json={'ratio_limit': 5, 'ratio_action': 'delete'}).status_code == 200
    app.extensions['runtime'].rpc.assert_called_once_with('ratio', {'hash': 'a' * 40, 'ratio_limit': 5})


def test_missing_torrent_cannot_change_another(monkeypatch):
    calls=[]
    def api(path,data=None):
        calls.append(path)
        return Mock(json=lambda: {'current_network_interface': 'tun0', 'upnp': False} if path=='app/preferences' else [])
    monkeypatch.setattr('qbit_rpc.call',api)
    with pytest.raises(ValueError):execute('ratio', {'hash':'a'*40,'ratio_limit':5})
    assert 'torrents/setShareLimits' not in calls
