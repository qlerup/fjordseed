"""Private, tool-free Codex transport shared in design with FjordLens."""
import os
import json
import queue
import subprocess
import threading
import time

LOGIN_ERROR = 'ChatGPT-forbindelsen kunne ikke gennemføres. Prøv igen.'

class CodexRPC:
    """Private stdio transport; server tool/approval requests are always rejected."""
    def __init__(self, home, executable):
        env = os.environ.copy()
        env['CODEX_HOME'] = str(home)
        for key in ['OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN']:
            env.pop(key, None)
        self.process = subprocess.Popen([executable, 'app-server', '--listen', 'stdio://',
                                         '-c', 'cli_auth_credentials_store="file"'],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, encoding='utf-8', env=env,
                                        cwd=str(home),
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.messages = queue.Queue()
        self.notifications = []
        self.sequence = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    self.messages.put(json.loads(line))
                except ValueError:
                    continue
        finally:
            self.messages.put(None)

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + '\n')
        self.process.stdin.flush()

    def request(self, method, params=None, timeout=20):
        if hasattr(self, 'deadline'):
            timeout = min(timeout, self.deadline - time.monotonic())
            if timeout <= 0:
                raise TimeoutError(LOGIN_ERROR)
        self.sequence += 1
        ident = self.sequence
        self.send(dict(id=ident, method=method, params=params or {}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self.messages.get(timeout=max(.01, deadline - time.monotonic()))
            if message is None:
                raise ValueError(LOGIN_ERROR)
            if message.get('id') == ident:
                if 'error' in message:
                    raise ValueError(LOGIN_ERROR)
                return message['result']
            if 'id' not in message:
                self.notifications.append(message)
            else:
                # This adapter implements no execution or approval capabilities.
                self.send(dict(id=message['id'], error={'code': -32601, 'message': 'Unsupported method'}))
        raise TimeoutError(LOGIN_ERROR)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        for pipe in [self.process.stdin, self.process.stdout]:
            pipe.close()

