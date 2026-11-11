import re

import pytest

from app import create_app
from safari_setup import build_userscript, validate_seed_origin
from test_app import FakeRuntime, login


@pytest.mark.parametrize('origin,host,expected', [
    ('https://seed.example', 'seed.example', 'https://seed.example'),
    ('https://SEED.example/', 'seed.example', 'https://seed.example'),
    ('https://seed.example:443', 'seed.example', 'https://seed.example'),
    ('https://seed.example', 'seed.example:443', 'https://seed.example'),
    ('http://seed.example:80/', 'seed.example', 'http://seed.example'),
    ('http://192.168.1.110:8099', '192.168.1.110:8099', 'http://192.168.1.110:8099'),
    ('https://seed.example:8443', 'seed.example:8443', 'https://seed.example:8443'),
])
def test_origin_preserves_browser_scheme_and_exact_nondefault_port(origin, host, expected):
    assert validate_seed_origin(origin, host, 'http') == expected


@pytest.mark.parametrize('origin', [
    'https://evil.example', 'https://seed.example.evil.example',
    'https://user@seed.example', 'https://user:secret@seed.example',
    'https://seed.example:8443', 'https://seed.example:0', 'https://seed.example:',
    'https://seed.example/login', 'https://seed.example//',
    'https://seed.example?key=secret', 'https://seed.example?',
    'https://seed.example#part', 'https://seed.example#',
    'http://seed.example:443', 'javascript:alert(1)', '//seed.example',
    'https://seed.example\n// @grant GM.xmlHttpRequest',
    'https://seed.example\\@evil.example', 'https://seed%2eexample',
    ' https://seed.example', '',
])
def test_origin_rejects_other_hosts_ports_and_metadata_injection(origin):
    with pytest.raises(ValueError):
        validate_seed_origin(origin, 'seed.example', 'http')


def test_bundle_is_self_contained_and_scope_keeps_exact_origin():
    source = build_userscript('https://seed.example:8443')
    assert source.startswith('// ==UserScript==\n')
    assert '// @name         FjordSeed · seed.example:8443\n' in source
    assert '// @match        https://seed.example/*\n' in source
    assert '// @match        https://seed.example:8443/*' not in source
    assert 'await startFjordSeedUserscript("https://seed.example:8443", ' in source
    assert '/browser/fjordseed.user.js?origin=https%3A%2F%2Fseed.example%3A8443' in source
    assert not re.search(r'^\s*(?:import|export)\b', source, re.MULTILINE)
    assert not re.search(r'^// @grant\s+GM[._]xml', source, re.MULTILINE)
    assert len(re.findall(r'^// @match\s', source, re.MULTILINE)) == 3


def test_script_is_public_but_application_and_mutations_still_require_auth(tmp_path, monkeypatch):
    monkeypatch.delenv('FJORDHUB_URL', raising=False)
    monkeypatch.setenv('FJORDHUB_API_KEY', 'private-api-key-must-not-enter-userscript')
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    client = app.test_client()
    response = client.get('/browser/fjordseed.user.js', query_string={'origin': 'https://localhost:8099'},
                          headers={'Host': 'localhost:8099'})
    assert response.status_code == 200
    assert response.mimetype == 'text/plain'
    assert response.headers['Content-Disposition'].startswith('inline;')
    assert 'Set-Cookie' not in response.headers
    source = response.get_data(as_text=True)
    assert 'await startFjordSeedUserscript("https://localhost:8099", ' in source
    assert 'private-api-key-must-not-enter-userscript' not in source
    assert app.extensions['state'].secret_path.read_text().strip() not in source
    assert client.get('/').status_code == 302
    assert client.get('/api/status').status_code == 401
    assert client.get('/api/manual-package').status_code == 401
    assert client.post('/api/torrents', json={}).status_code == 403
    assert client.get('/browser/fjordseed.user.js?origin=https://evil.example').status_code == 400
    assert client.get('/browser/fjordseed.user.js?origin=http://localhost&origin=https://localhost').status_code == 400
    assert client.get('/browser/fjordseed.user.js', headers={'Host': 'evil.example'}).status_code == 403
    app.extensions['runtime'].rpc.assert_not_called()


def test_setup_starts_hidden_and_preserves_chrome_download(tmp_path):
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    client, _ = login(app)
    html = client.get('/').get_data(as_text=True)
    assert re.search(r'<button\b[^>]*id="safari-setup-open"[^>]*\bhidden', html)
    assert 'href="/static/fjordseed-chrome.zip" download' in html
    assert 'https://apps.apple.com/dk/app/userscripts/id1463298887' in html
    assert 'Installér FjordSeed i Userscripts' in html
    assert 'TestFlight' not in html
    assert 'safari-setup.mjs' in html
