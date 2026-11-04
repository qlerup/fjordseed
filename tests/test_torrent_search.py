from unittest.mock import Mock
import base64
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from app import create_app
from test_app import FakeRuntime, login
from torrent_search import ENGINES, execute, plugin_metadata
import qbit_rpc


@pytest.fixture
def setup(tmp_path):
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    client, headers = login(app)
    app.extensions['state'].save('a'*32, True)
    runtime = app.extensions['runtime']
    def rpc(action, data):
        if action == 'search-start': return {'id': 123}
        if action == 'search-results': return {'status': 'Stopped', 'total': 1, 'results': []}
        return {'ok': True}
    runtime.rpc.side_effect = rpc
    return app, client, headers, runtime


def test_auth_csrf_disabled_and_session_ownership(setup):
    app, client, headers, runtime = setup
    assert app.test_client().get('/api/search/plugins').status_code == 401
    assert client.post('/api/search', json={'pattern': 'Ubuntu'}).status_code == 403
    app.extensions['state'].save('a'*32, False)
    assert client.get('/api/search/plugins').status_code == 409
    runtime.rpc.assert_not_called()
    app.extensions['state'].save('a'*32, True)
    token = client.post('/api/search', headers=headers, json={'pattern': 'Ubuntu'}).json['token']
    assert client.get('/api/search/'+token).status_code == 200
    other, _ = login(app)
    assert other.get('/api/search/'+token).status_code == 404
    assert client.post('/api/search/'+token, headers=headers, json={'action': 'downloadTorrent'}).status_code == 409
    assert client.get('/api/search/'+token+'?offset=no').status_code == 409


def test_replaces_old_job_and_resolves_without_starting_download(setup):
    _, client, headers, runtime = setup
    first = client.post('/api/search', headers=headers, json={'pattern': 'Ubuntu'}).json['token']
    second = client.post('/api/search', headers=headers, json={'pattern': 'Debian'}).json['token']
    runtime.rpc.assert_any_call('search-delete', {'id': 123})
    assert client.get('/api/search/'+first).status_code == 404
    response = client.post('/api/search/'+second, headers=headers, json={'action': 'resolve', 'offset': 5})
    assert response.status_code == 200
    runtime.rpc.assert_called_with('search-resolve', {'id': 123, 'offset': 5})
    assert not any(c.args[0] == 'add' for c in runtime.rpc.call_args_list)
    assert client.post('/api/search/'+second, headers=headers, json={'action': 'delete'}).status_code == 200
    assert client.get('/api/search/'+second).status_code == 404


@pytest.mark.parametrize('as_file',[False,True])
def test_copy_magnet_resolves_exact_result_without_starting_download(setup,as_file):
    _,client,headers,runtime=setup
    token=client.post('/api/search',headers=headers,json={'pattern':'Ubuntu'}).json['token']
    magnet='magnet:?xt=urn:btih:'+'a'*40+'&dn=Ubuntu'
    raw=b'd8:announce32:https://tracker.example/announce4:infod6:lengthi1e4:name6:Ubuntu12:piece lengthi16384e6:pieces20:aaaaaaaaaaaaaaaaaaaaee'
    source={'torrent':base64.b64encode(raw).decode()} if as_file else {'magnet':magnet}
    runtime.rpc.side_effect=lambda action,data:{**source,'_search_session':{'SID':'private-fixture'}}
    response=client.post('/api/search/'+token,headers=headers,json={'action':'magnet','offset':40})
    assert response.status_code==200
    params=parse_qs(urlsplit(response.json['magnet']).query)
    assert params['dn']==['Ubuntu']
    if as_file:
        assert params['tr']==['https://tracker.example/announce']
        assert params['xt'][0].startswith('urn:btih:')
    else:assert response.json=={'magnet':magnet}
    assert 'private-fixture' not in str(response.json)
    runtime.rpc.assert_called_with('search-resolve',{'id':123,'offset':40})
    assert not any(c.args[0]=='add' for c in runtime.rpc.call_args_list)


def test_expiry_and_restart_cleanup(setup, monkeypatch):
    _, client, headers, runtime = setup
    monkeypatch.setattr('search_routes.time.monotonic', lambda: 0)
    token = client.post('/api/search', headers=headers, json={'pattern': 'Ubuntu'}).json['token']
    monkeypatch.setattr('search_routes.time.monotonic', lambda: 601)
    assert client.get('/api/search/'+token).status_code == 409
    runtime.rpc.assert_called_with('search-delete', {'id': 123})
    error = requests.HTTPError(response=Mock(status_code=404))
    assert execute('search-delete', {'id': 123}, Mock(side_effect=error)) == {'ok': True}


def test_engine_and_query_allowlist_and_pagination():
    api = Mock(return_value=Mock(json=lambda: [{'name': 'piratebay', 'enabled': True}]))
    for data in ({'pattern': ''}, {'pattern': 'x'*201}, {'pattern': []}, {'pattern': 'ok', 'plugin': 'file:///etc/passwd'}):
        with pytest.raises(ValueError): execute('search-start', data, api)
    for name in ('jackett', 'https://evil.test/plugin.py', '../evil', None):
        with pytest.raises(ValueError): execute('search-install', {'name': name}, api)
    execute('search-install', {'name': 'torrentscsv'}, api)
    assert api.call_args.args == ('search/installPlugin', {'sources': 'https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/torrentscsv.py'})
    execute('search-start', {'pattern': ' Ubuntu ', 'plugin': 'piratebay'}, api)
    assert api.call_args.args == ('search/start', {'pattern': 'Ubuntu', 'plugins': 'piratebay', 'category': 'all'})
    api.return_value = Mock(json=lambda: {'results': [], 'total': 0, 'status': 'Stopped'})
    execute('search-results', {'id': 123, 'offset': 50}, api)
    assert parse_qs(urlsplit(api.call_args.args[0]).query) == {'id': ['123'], 'offset': ['50'], 'limit': ['10']}
    for value in (-1, True, '50', 2147483648):
        with pytest.raises(ValueError): execute('search-results', {'id': 123, 'offset': value}, api)


def test_only_selected_native_result_can_supply_metadata(monkeypatch):
    magnet = 'magnet:?xt=urn:btih:'+'a'*40
    api = Mock(return_value=Mock(json=lambda: {'results': [{'fileUrl': magnet, 'fileName': 'Ubuntu'}]}))
    fetch = Mock(return_value=({}, {'magnet': magnet}))
    monkeypatch.setattr('rss_gate.fetch_metadata', fetch)
    result = execute('search-resolve', {'id': 1, 'offset': 3, 'url': 'https://evil.test'}, api)
    assert result == {'name': 'Ubuntu', 'magnet': magnet}
    fetch.assert_called_once_with(magnet)
    assert 'limit=1' in api.call_args.args[0]
    fetch.side_effect = ValueError('private detail')
    monkeypatch.setattr('torrent_search.plugin_metadata', Mock(side_effect=ValueError('secret')))
    with pytest.raises(ValueError, match='Torrentlinket kunne ikke hentes'):
        execute('search-resolve', {'id': 1}, api)


def test_bulk_install_adds_missing_and_enables_disabled_catalog_engines_only():
    installed = [{'name': 'eztv', 'enabled': True}, {'name': 'piratebay', 'enabled': False},
                 {'name': 'private_tracker', 'enabled': False}]
    api = Mock(return_value=Mock(json=lambda: installed))
    result = execute('search-install', {'name': 'all'}, api)
    assert result == {'ok': True, 'requested': list(ENGINES)}
    api.assert_any_call('search/enablePlugin', {'names': 'piratebay', 'enable': 'true'})
    sources = api.call_args.args[1]['sources'].split('|')
    expected = [n for n in ENGINES if n not in ('eztv', 'piratebay')]
    assert sources == [f'https://raw.githubusercontent.com/qbittorrent/search-plugins/master/nova3/engines/{n}.py' for n in expected]
    assert all('private_tracker' not in str(c) for c in api.call_args_list)


def test_bulk_install_is_idempotent_and_default_search_uses_all_enabled_engines():
    api = Mock(return_value=Mock(json=lambda: [{'name': n, 'enabled': True} for n in ENGINES]))
    execute('search-install', {'name': 'all'}, api)
    assert api.call_count == 1 and api.call_args.args == ('search/plugins',)
    execute('search-start', {'pattern': 'Ubuntu'}, api)
    assert api.call_args.args == ('search/start', {'pattern': 'Ubuntu', 'plugins': 'enabled', 'category': 'all'})


def test_vpn_binding_checked_before_search(monkeypatch):
    api = Mock(return_value=Mock(json=lambda: {'current_network_interface': 'eth0', 'upnp': False}))
    monkeypatch.setattr(qbit_rpc, 'call', api)
    with pytest.raises(RuntimeError): qbit_rpc.execute('search-start', {'pattern': 'Ubuntu'})
    assert api.call_count == 1


def test_custom_plugin_metadata_is_bounded_and_validated(tmp_path, monkeypatch):
    (tmp_path/'engines').mkdir()
    (tmp_path/'engines'/'example.py').touch()
    raw = b'd4:infod6:lengthi1e4:name6:Ubuntuee'
    def run(args, **kwargs):
        directory = kwargs['env']['TMPDIR']
        path = __import__('pathlib').Path(directory)/'test.torrent'
        path.write_bytes(raw)
        assert args[-2:] == ['example', 'https://example.test/details/1']
        assert kwargs['timeout'] == 15
        return Mock(returncode=0, stdout=str(path)+' https://example.test/file')
    monkeypatch.setattr('torrent_search.subprocess.run', run)
    row = {'engineName': 'example', 'fileUrl': 'https://example.test/details/1'}
    assert 'torrent' in plugin_metadata(row, tmp_path)
    with pytest.raises(ValueError): plugin_metadata({**row, 'engineName': '../evil'}, tmp_path)


def test_seeders_filter_precedes_pagination_and_keeps_native_result_indices():
    rows = [{'fileName': f'Fixture {i}', 'nbSeeders': -1 if i == 0 else i} for i in range(35)]
    api = Mock(return_value=Mock(json=lambda: {'results': rows, 'total': 35, 'status': 'Running'}))
    result = execute('search-results', {'id': 123, 'offset': 10, 'min_seeders': 15}, api)
    assert parse_qs(urlsplit(api.call_args.args[0]).query) == {'id': ['123'], 'offset': ['0'], 'limit': ['0']}
    assert result['total'] == 20 and result['unfiltered_total'] == 35
    assert result['status'] == 'Running' and result['min_seeders'] == 15
    assert [r['result_index'] for r in result['results']] == list(range(25, 35))
    assert all(r['nbSeeders'] >= 15 for r in result['results'])
    result = execute('search-results', {'id': 123, 'offset': 0, 'min_seeders': 40}, api)
    assert result['total'] == 0 and result['results'] == []
    for minimum in (-1, True, '5', 1000001, 1.5):
        with pytest.raises(ValueError):
            execute('search-results', {'id': 123, 'min_seeders': minimum}, api)


def test_unfiltered_results_keep_unknown_seeders_and_their_download_index():
    api = Mock(return_value=Mock(json=lambda: {
        'results': [{'nbSeeders': -1}, {'nbSeeders': 0}], 'total': 12, 'status': 'Stopped'}))
    result = execute('search-results', {'id': 123, 'offset': 10}, api)
    assert [r['result_index'] for r in result['results']] == [10, 11]
    assert result['total'] == 12 and result['min_seeders'] == 0


def test_minimum_seeders_route_validation_and_filter_forwarding(setup):
    _, client, headers, runtime = setup
    token = client.post('/api/search', headers=headers, json={'pattern': 'Ubuntu'}).json['token']
    response = client.get('/api/search/'+token+'?offset=10&min_seeders=5')
    assert response.status_code == 200
    runtime.rpc.assert_called_with('search-results', {'id': 123, 'offset': 10, 'min_seeders': 5})
    for value in ('-1', '1.5', 'abc', '1000001'):
        assert client.get('/api/search/'+token+'?min_seeders='+value).status_code == 409
