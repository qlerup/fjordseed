import json
import os
from pathlib import Path
import secrets
import threading
import uuid


def atomic(path, data, mode=0o600):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class State:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.lock = threading.RLock()
        self.path = self.root / 'settings.json'
        if not self.path.exists():
            atomic(self.path, json.dumps({'id':uuid.uuid4().hex, 'profile_id':'', 'enabled':False}))
        self.secret_path = self.root / 'session-secret'
        if not self.secret_path.exists():
            atomic(self.secret_path, secrets.token_hex(32))

    def get(self):
        with self.lock:
            return json.loads(self.path.read_text(encoding='utf-8'))

    def save(self, profile_id, enabled):
        with self.lock:
            data = self.get()
            data.update(profile_id=profile_id, enabled=enabled)
            atomic(self.path, json.dumps(data))
            return data
