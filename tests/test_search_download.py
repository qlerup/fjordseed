import json
from pathlib import Path
from unittest.mock import Mock

from app import create_app
import download_storage as storage
from green_credit import CreditLedger
from qbit_rpc import execute, sync_share_limits
from test_app import FakeRuntime, login


HASH = 'a'*40
MAGNET = 'magnet:?xt=urn:btih:'+HASH+'&dn=Example.Film'


def test_search_download_enforces_stop_keep_and_deduplicates_successful_requests(tmp_path):
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    client, headers = login(app)
    app.extensions['state'].save('a'*32, True)
    runtime = app.extensions['runtime']
    runtime.rpc.return_value = {'id': 123, '_search_session': {'SID': 'private'}}
    token = client.post('/api/search', headers=headers, json={'pattern': 'Example'}).json['token']
    runtime.rpc.reset_mock()
    runtime.rpc.side_effect = [dict(magnet=MAGNET, name='Example Film', _search_session={'SID': 'refreshed'}), {'ok': True}]
    data = {'action': 'download', 'offset': 50, 'ratio_action': 'delete', 'ratio_limit': 10, 'convert': True}
    response = client.post('/api/search/'+token, headers=headers, json=data)
    assert response.status_code == 200 and response.json == {'ok': True, 'name': 'Example Film'}
    assert runtime.rpc.call_args_list[0].args == ('search-resolve', {'id': 123, 'offset': 50, '_search_session': {'SID': 'private'}})
    assert runtime.rpc.call_args_list[1].args == ('add', {'magnet': MAGNET,
        'ratio_action': 'stop_keep', 'ratio_limit': 1.0, 'convert': False})
    assert client.post('/api/search/'+token, headers=headers, json=data).json['already_added'] is True
    assert runtime.rpc.call_count == 2
    assert 'SID' not in response.get_data(as_text=True)


def test_failed_search_add_can_be_retried_and_requires_csrf(tmp_path):
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    client, headers = login(app)
    app.extensions['state'].save('a'*32, True)
    runtime = app.extensions['runtime']
    runtime.rpc.return_value = {'id': 123}
    token = client.post('/api/search', headers=headers, json={'pattern': 'Example'}).json['token']
    runtime.rpc.side_effect = [dict(magnet=MAGNET), ValueError('Unavailable'), dict(magnet=MAGNET), {'ok': True}]
    data = {'action': 'download', 'offset': 0}
    assert client.post('/api/search/'+token, json=data).status_code == 403
    assert client.post('/api/search/'+token, headers=headers, json=data).status_code == 409
    assert client.post('/api/search/'+token, headers=headers, json=data).status_code == 200


def test_search_policy_stops_then_moves_complete_files_to_configured_library(tmp_path, monkeypatch):
    library = tmp_path/'FjordFlix-Plex'
    monkeypatch.setattr(storage, 'download_root', lambda: library)
    settings = tmp_path/'download-settings.json'
    settings.write_text(json.dumps({'streaming_enabled': True}))
    monkeypatch.setattr(storage, 'SETTINGS', settings)
    row = {'hash': HASH, 'name': 'Example.Film', 'state': 'downloading', 'progress': .5,
           'ratio_limit': -1, 'share_limit_action': 'Stop', 'seeding_time_limit': -1,
           'inactive_seeding_time_limit': -1, 'ratio': 0, 'seeding_time': 0}

    def api(path, data=None, files=None):
        if path == 'app/preferences': return Mock(json=lambda: {'current_network_interface': 'tun0', 'upnp': False})
        if path == 'torrents/info': return Mock(json=lambda: [row])
        if path == 'torrents/add':
            assert data['shareLimitAction'] == 'Stop' and data['forceStart'] == 'false'
            row['save_path'] = data['savepath']
            Path(row['save_path'], 'movie.mkv').write_bytes(b'kept-content')
            return Mock(text='Ok.')
        if path == 'torrents/stop': row['state'] = 'stoppedUP'
        if path == 'torrents/setLocation':
            assert row['state'] == 'stoppedUP'
            source, destination = Path(row['save_path']), Path(data['location'])
            (source/'movie.mkv').replace(destination/'movie.mkv')
            row['save_path'] = str(destination)
        assert path not in ('torrents/delete', 'torrents/start')
        return Mock()

    native = Mock(side_effect=api)
    monkeypatch.setattr('qbit_rpc.call', native)
    execute('add', {'magnet': MAGNET, 'ratio_action': 'stop_keep', 'ratio_limit': 1, 'convert': False})
    with CreditLedger().transaction() as ledger:
        assert ledger.update(row)['stop_on_complete'] is True
    native.reset_mock()
    sync_share_limits(native)
    assert not any(c.args[0] in ('torrents/stop', 'torrents/setLocation') for c in native.call_args_list)
    row.update(progress=1, state='uploading')
    native.reset_mock()
    sync_share_limits(native)
    paths = [c.args[0] for c in native.call_args_list]
    assert paths.index('torrents/stop') < paths.index('torrents/setLocation')
    sync_share_limits(native)
    assert row['state'] == 'stoppedUP'
    assert Path(row['save_path']).parent == library
    assert Path(row['save_path'], 'movie.mkv').read_bytes() == b'kept-content'
    assert not Path(row['save_path'], storage.PUBLISHING_MARKER).exists()
