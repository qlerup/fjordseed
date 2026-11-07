import json
import queue
import time
from pathlib import Path

import pytest

import subtitle_device_auth as device


class FakeRPC:
    url = 'https://auth.openai.com/codex/device'
    success = True
    callback = None

    def __init__(self, home, executable):
        self.home = Path(home)
        self.messages = queue.Queue()
        self.notifications = []
        self.closed = False

    def request(self, method, params=None, **kwargs):
        if method == 'account/login/start':
            self.notifications.append({'method': 'account/login/completed', 'params': {'loginId': 'login', 'success': self.success}})
            (self.home/'auth.json').write_text(json.dumps({'tokens': {'access_token': 'secret', 'account_id': 'account'}}))
            return {'verificationUrl': self.url, 'userCode': 'ABCD-1234', 'loginId': 'login'}
        if method == 'account/read':
            if type(self).callback:
                type(self).callback()
            return {'account': {'type': 'chatgpt', 'email': 'user@example.test'}}
        return {}

    def send(self, message):
        pass

    def close(self):
        self.closed = True


def prepare(tmp_path, monkeypatch):
    monkeypatch.setattr(device, 'CodexRPC', FakeRPC)
    monkeypatch.setattr(FakeRPC, 'url', 'https://auth.openai.com/codex/device')
    monkeypatch.setattr(FakeRPC, 'success', True)
    monkeypatch.setattr(FakeRPC, 'callback', None)
    auth = device.ChatGPT(tmp_path)
    auth.logins['alice'] = dict(attempt='attempt', state='starting', expires_at=time.time()+600)
    return auth


def test_login_saves_only_for_owner_and_never_exposes_tokens(tmp_path, monkeypatch):
    auth = prepare(tmp_path, monkeypatch)
    auth._login('alice', 'attempt', 'codex')
    status = auth.status('alice')
    assert status['connected'] and status['enabled']
    assert status['login']['state'] == 'completed'
    assert status['login']['user_code'] is None
    assert 'secret' not in json.dumps(status)
    assert not auth.status('bob')['connected']
    assert 'login' not in auth.status('bob')
    auth.disconnect('alice')
    assert not auth.status('alice')['connected']


@pytest.mark.parametrize('url', ['http://auth.openai.com/code', 'https://evil.test/code', 'https://auth.openai.com@evil.test/code'])
def test_untrusted_login_links_are_rejected(tmp_path, monkeypatch, url):
    auth = prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(FakeRPC, 'url', url)
    auth._login('alice', 'attempt', 'codex')
    assert auth.status('alice')['login']['state'] == 'failed'
    assert not auth.status('alice')['connected']


def test_cancelled_login_cannot_restore_account(tmp_path, monkeypatch):
    auth = prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(FakeRPC, 'callback', lambda: auth.device_cancel('alice'))
    auth._login('alice', 'attempt', 'codex')
    assert not auth.status('alice')['connected']


def test_expiry_removes_visible_code(tmp_path):
    auth = device.ChatGPT(tmp_path)
    auth.logins['alice'] = dict(state='waiting', expires_at=0, user_code='OLD', verification_url='https://auth.openai.com/code')
    assert auth.status('alice')['login']['state'] == 'expired'
    assert auth.status('alice')['login']['user_code'] is None


def test_translation_keeps_timing_and_sends_text_only(tmp_path, monkeypatch):
    from contextlib import contextmanager
    auth = device.ChatGPT(tmp_path)
    monkeypatch.setattr(auth, '_is_device', lambda *_: True)
    calls = []
    class TranslationRPC(FakeRPC):
        deadline = time.monotonic()+10
        def request(self, method, params=None, **kwargs):
            calls.append((method, params))
            if method == 'thread/start':
                return {'thread': {'id': 'thread'}}
            self.notifications.append({'method': 'turn/completed', 'params': {'threadId': 'thread', 'turn': {
                'id': 'turn', 'status': 'completed', 'items': [{'id': 'reply', 'type': 'agentMessage',
                'text': json.dumps({'cues': [{'id': 1, 'text': 'Hej'}]})}]}}})
            return {'turn': {'id': 'turn'}}
    @contextmanager
    def connected(*_):
        yield TranslationRPC(tmp_path, ''), tmp_path
    monkeypatch.setattr(auth, '_connected', connected)
    cues = [{'id': 1, 'text': 'Hello', 'timing': '00:00:01,000 --> 00:00:02,000'}]
    result = auth.translate('alice', 'account', 'model', 'da', cues)
    assert result[0]['timing'] == cues[0]['timing']
    assert result[0]['text'] == 'Hej'
    assert '00:00:' not in json.dumps(calls)
    assert calls[0][1]['sandbox'] == 'read-only'
