"""Owner-scoped asynchronous audio analysis and preview assets."""
import json
import logging
from pathlib import Path
import re
import threading
import time
import uuid

from state import atomic
from merge_progress import snapshot

ASSETS = ('base.mp4', 'donor.m4a')


class Checks:
    def __init__(self, root, runtime):
        self.root = root/'merge-checks'; self.root.mkdir(parents=True, exist_ok=True)
        self.media = root/'qbit'/'merge-previews'
        self.path = self.root/'jobs.json'; self.runtime = runtime; self.lock = threading.RLock()
        with self.lock:
            rows = self.read()
            for row in rows:
                if row['state'] == 'running': row.update(state='error', finished_at=time.time(), detail='Serveren blev genstartet. Start kontrollen igen.')
            self.save(rows)

    def read(self): return json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else []
    def save(self, rows): atomic(self.path, json.dumps(rows, ensure_ascii=False))

    def cleanup(self, rows):
        keep = []
        for row in rows:
            if row['state'] in ('queued', 'running') or time.time()-row['created_at'] < 3600:
                keep.append(row); continue
            directory = self.media/row['id']
            if (re.fullmatch('[a-f0-9]{32}', row['id']) and not self.media.is_symlink()
                    and not directory.is_symlink() and directory.is_dir()):
                for name in (*ASSETS, 'donor.mp4', 'progress.json', 'video.ffmpeg', 'audio.ffmpeg'):
                    (directory/name).unlink(missing_ok=True)
                try: directory.rmdir()
                except OSError: pass
        return keep

    def enqueue(self, owner, data):
        if not isinstance(data, dict) or data.get('kind') not in ('analyse', 'preview'):
            raise ValueError('Vælg lydmatch eller prøveklip.')
        # Media-side validation resolves all paths and track IDs before reading.
        if not all(isinstance(data.get(key), dict) for key in ('base', 'donor')):
            raise ValueError('Vælg to film først.')
        with self.lock:
            rows = self.cleanup(self.read())
            active = [r for r in rows if r['state'] in ('queued', 'running')]
            if any(r['owner'] == owner for r in active): raise ValueError('Vent til din igangværende kontrol er færdig.')
            if len(active) >= 10 or len(rows) >= 100: raise ValueError('Der er mange kontroller i kø. Prøv igen senere.')
            row = {'id': uuid.uuid4().hex, 'owner': owner, 'state': 'queued', 'created_at': time.time(),
                   'detail': 'Venter på kontrol', 'request': data}
            rows.append(row); self.save(rows)
        return {'id': row['id'], 'state': row['state']}

    def owned(self, owner, ident):
        if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident): raise ValueError('Kontrollen findes ikke.')
        row = next((r for r in self.read() if r['id'] == ident and r['owner'] == owner), None)
        if not row: raise ValueError('Kontrollen findes ikke.')
        return row

    def status(self, owner, ident):
        with self.lock: row = self.owned(owner, ident)
        result = {k: row.get(k) for k in ('id', 'state', 'detail', 'result')}
        if row['state'] != 'queued':
            result['elapsed_seconds'] = max(0, int((row.get('finished_at') or time.time())-row.get('started_at', row['created_at'])))
        if row['state'] == 'running':
            result.update(snapshot(self.media/ident))
        elif row['state'] == 'done': result['progress'] = 100
        return result

    def asset(self, owner, ident, name):
        with self.lock: row = self.owned(owner, ident)
        if row['state'] != 'done' or row.get('result', {}).get('kind') != 'preview' or name not in ASSETS:
            raise ValueError('Prøveklippet er ikke klar.')
        path = self.media/ident/name
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise ValueError('Prøveklippet er udløbet. Lav et nyt.')
        return path

    def update(self, ident, **fields):
        with self.lock:
            rows = self.read(); row = next(r for r in rows if r['id'] == ident)
            if fields.get('state') in ('done', 'error'): fields.setdefault('finished_at', time.time())
            row.update(fields); self.save(rows)

    def run_once(self):
        with self.lock:
            original = self.read()
            rows = self.cleanup(original)
            row = next((r for r in rows if r['state'] == 'queued'), None)
            if row: row.update(state='running', started_at=time.time(), detail='Klargør kontrol')
            if row or len(rows) != len(original): self.save(rows)
        if not row: return
        try:
            result = self.runtime.rpc('library-merge-'+row['request']['kind'], {**row['request'], 'check_id': row['id']})
            self.update(row['id'], state='done', result=result, detail=result['detail'])
        except ValueError as exc: self.update(row['id'], state='error', detail=str(exc))
        except Exception:
            logging.getLogger(__name__).exception('Merge check failed')
            self.update(row['id'], state='error', detail='Kontrollen blev afbrudt. Prøv igen.')

    def run(self, stop):
        while not stop.wait(1): self.run_once()
