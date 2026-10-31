"""Authenticated per-user manual drafts; never starts torrents or fetches URLs."""
import base64
import hashlib
import json
import re
import time
import uuid

from state import atomic
from torrent_meta import torrent_meta


class ManualPackage:
    MAX_FILES = 50
    MAX_TOTAL = 32 * 1024 * 1024

    def __init__(self, state):
        self.state = state
        self.root = state.root / 'manual-packages'

    def path(self, owner):
        return self.root / (hashlib.sha256(str(owner).encode()).hexdigest() + '.json')

    def read(self, owner):
        try:
            return json.loads(self.path(owner).read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {'items': [], 'completed': []}

    def write(self, owner, data):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic(self.path(owner), json.dumps(data))

    def public(self, owner):
        with self.state.lock:
            entries = self.read(owner)['items']
            return {'count': len(entries), 'items': [
                {key: entry[key] for key in ('id', 'name', 'size', 'created')} for entry in entries]}

    def add(self, owner, raw, filename):
        if not isinstance(filename, str) or not filename.lower().endswith('.torrent'):
            raise ValueError('Torrentpakken accepterer kun .torrent-filer, ikke RSS-links.')
        if not raw or len(raw) > 4 * 1024 * 1024:
            raise ValueError('Torrentfilen må højst fylde 4 MiB.')
        meta = torrent_meta(raw)
        name = re.sub(r'[\x00-\x1f\x7f/\\]', '_', filename)[:240]
        with self.state.lock:
            data = self.read(owner)
            if any(set(meta['hashes']) & set(item['hashes']) for item in data['items']):
                return {**self.public(owner), 'duplicate': True}
            if len(data['items']) >= self.MAX_FILES or sum(e['size'] for e in data['items']) + len(raw) > self.MAX_TOTAL:
                raise ValueError('Pakken er fuld. Start eller ryd den først (højst 50 filer / 32 MiB).')
            data['items'].append({'id': uuid.uuid4().hex, 'name': name, 'size': len(raw),
                                  'hashes': meta['hashes'], 'created': time.time(),
                                  'base64': base64.b64encode(raw).decode('ascii')})
            self.write(owner, data)
            return {**self.public(owner), 'duplicate': False}

    def get(self, owner, ident):
        if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident):
            raise ValueError('Ugyldigt pakkeelement.')
        with self.state.lock:
            return next((item for item in self.read(owner)['items'] if item['id'] == ident), None)

    def remove(self, owner, ids, completed=False):
        if (not isinstance(ids, list) or len(ids) > self.MAX_FILES or
                any(not isinstance(i, str) or not re.fullmatch('[a-f0-9]{32}', i) for i in ids)):
            raise ValueError('Vælg gyldige filer fra pakken.')
        with self.state.lock:
            data = self.read(owner)
            data['items'] = [item for item in data['items'] if item['id'] not in ids]
            if completed:
                data['completed'] = list(dict.fromkeys(data.get('completed', []) + ids))[-100:]
            self.write(owner, data)
            return self.public(owner)
