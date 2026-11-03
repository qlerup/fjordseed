"""Real HTTP regression for qBittorrent's per-WebUI-session search jobs."""
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from app import create_app
import qbit_rpc
import qbit_worker
from test_app import FakeRuntime, login


@pytest.fixture
def native_api(monkeypatch):
    sessions, calls = {}, []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass

        def handle_api(self):
            parsed = urlsplit(self.path)
            data = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode()) if self.command == 'POST' else parse_qs(parsed.query)
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            cookie = cookies.get('QBT_SID_test')
            sid = cookie.value if cookie else ''
            if sid not in sessions:
                sid = f'session-{len(sessions)}'
                sessions[sid] = {}
            calls.append((parsed.path, sid))
            status, result = 200, {}
            if parsed.path.endswith('/app/preferences'):
                result = {'current_network_interface': 'tun0', 'upnp': False}
            elif parsed.path.endswith('/search/plugins'):
                result = [{'name': 'torrentscsv', 'enabled': True}]
            elif parsed.path.endswith('/search/start'):
                sessions[sid][123] = {'fileName': 'Ubuntu fixture', 'fileUrl': 'magnet:?xt=urn:btih:'+'a'*40}
                result = {'id': 123}
            elif parsed.path.endswith('/search/results'):
                row = sessions[sid].get(int(data['id'][0]))
                if row:
                    result = {'results': [row], 'status': 'Stopped', 'total': 1}
                else:
                    status = 404
            elif parsed.path.endswith('/search/delete'):
                sessions[sid].pop(int(data['id'][0]), None)
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Set-Cookie', f'QBT_SID_test={sid}; Path=/; HttpOnly')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        do_GET = do_POST = handle_api

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(qbit_rpc, 'BASE', f'http://127.0.0.1:{server.server_port}/api/v2/')
    monkeypatch.setattr(qbit_worker, 'ready', Mock())
    monkeypatch.setattr('green_credit.pause_seed_health', Mock())
    try:
        yield calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_search_survives_separate_rpc_calls_using_private_webui_session(native_api):
    # Reproduce the old failure: two short-lived HTTP clients see different jobs.
    qbit_rpc.call('search/start', {'pattern': 'Ubuntu', 'plugins': 'enabled', 'category': 'all'})
    with pytest.raises(requests.HTTPError):
        qbit_rpc.call('search/results?id=123&offset=0&limit=50')

    started = qbit_rpc.execute('search-start', {'pattern': 'Ubuntu'})
    cookies = started['_search_session']
    assert cookies['QBT_SID_test']
    result = qbit_rpc.execute('search-results', {'id': started['id'], '_search_session': cookies})
    assert result['results'][0]['fileName'] == 'Ubuntu fixture'
    search_calls = [(path, sid) for path, sid in native_api if '/search/' in path]
    assert len({sid for _, sid in search_calls[-3:]}) == 1
    qbit_rpc.execute('search-delete', {'id': started['id'], '_search_session': cookies})
    with pytest.raises(ValueError, match='Start en ny søgning'):
        qbit_rpc.execute('search-results', {'id': started['id'], '_search_session': cookies})


@pytest.mark.parametrize('action', ['search-start', 'search-install', 'search-resolve'])
def test_outbound_search_work_is_blocked_before_any_search_request_without_vpn(native_api, monkeypatch, action):
    monkeypatch.setattr(qbit_worker, 'ready', Mock(side_effect=ValueError('VPN is not ready')))
    with pytest.raises(ValueError, match='VPN-forbindelsen er ikke klar'):
        qbit_rpc.execute(action, {'pattern': 'Ubuntu', 'name': 'all', 'id': 123})
    assert all(path.endswith('/app/preferences') for path, _ in native_api)


def test_private_native_session_stays_on_server_and_cannot_be_supplied_by_browser(tmp_path):
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    client, headers = login(app)
    app.extensions['state'].save('a'*32, True)
    runtime = app.extensions['runtime']
    secret = {'QBT_SID_test': 'private-native-cookie'}
    runtime.rpc.return_value = {'id': 123, '_search_session': secret}
    started = client.post('/api/search', headers=headers, json={
        'pattern': 'Ubuntu', '_search_session': {'SID': 'injected'}})
    token = started.json['token']
    runtime.rpc.assert_called_with('search-start', {'pattern': 'Ubuntu', 'plugin': 'enabled'})
    assert 'private-native-cookie' not in started.get_data(as_text=True)
    runtime.rpc.return_value = {'results': [], 'status': 'Stopped', 'total': 0, '_search_session': secret}
    response = client.get('/api/search/'+token)
    runtime.rpc.assert_called_with('search-results', {'id': 123, 'offset': 0, '_search_session': secret})
    assert '_search_session' not in response.json and 'private-native-cookie' not in response.get_data(as_text=True)
    assert '_search_session' not in client.get('/api/search/plugins').json
    assert '_search_session' not in client.post('/api/search/plugins', headers=headers,
        json={'name': 'all', '_search_session': secret}).json
    runtime.rpc.assert_called_with('search-install', {'name': 'all'})
    client.post('/api/search/'+token, headers=headers, json={'action': 'stop', '_search_session': {'SID': 'injected'}})
    runtime.rpc.assert_called_with('search-stop', {'id': 123, 'offset': 0, '_search_session': secret})
