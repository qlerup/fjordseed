"""New torrents are staged privately; qBittorrent moves retained complete payloads."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import threading
import uuid

from state import atomic

CONFIG = Path('/config')
BUFFER = '.fjordseed-buffer'
_lock = threading.RLock()


def read(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


@contextmanager
def transaction():
    CONFIG.mkdir(parents=True, exist_ok=True)
    with _lock, (CONFIG/'download-storage.lock').open('a+') as handle:
        try:
            import fcntl
        except ImportError:
            fcntl = None
        if fcntl:
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            entries = read(CONFIG/'download-storage.json', {})
            yield entries
            atomic(CONFIG/'download-storage.json', json.dumps(entries))
        finally:
            if fcntl:
                fcntl.flock(handle, fcntl.LOCK_UN)


def download_root():
    settings = read(Path('/rpc/download-settings.json'), {})
    root = Path(settings.get('path', '/downloads'))
    if root != Path('/downloads') and not re.fullmatch(r'/download-locations/[a-f0-9]{32}', root.as_posix()):
        raise ValueError('Ugyldig downloadplacering.')
    return root


def prepare(hashes, folder=''):
    """Capture destination at add time, including across default-folder changes."""
    from rss import folder_path
    root = download_root()
    target = folder_path(folder, root)
    with transaction() as entries:
        # A repeated add must never overwrite an existing destination or policy.
        record = next((entries[h] for h in hashes if h in entries), None)
        if record is None:
            token = uuid.uuid4().hex
            stage = root/BUFFER/token
            if (root/BUFFER).is_symlink():
                raise ValueError('Buffermappen må ikke være et link.')
            stage.mkdir(parents=True, exist_ok=False)
            record = {'stage': str(stage), 'target': str(target/token), 'published': False}
            for ident in hashes:
                entries[ident] = record
        return record['stage']


def forget(hashes):
    """Allow a later re-add to capture the current default, never remove payloads."""
    with transaction() as entries:
        stages = {entries[h]['stage'] for h in hashes if h in entries}
        for ident in list(entries):
            if entries[ident]['stage'] in stages:
                entries.pop(ident)
        for value in stages:
            try:
                Path(value).rmdir()  # Empty directories only; manual removal retains data.
            except OSError:
                pass


def publish_complete(api, rows):
    """Existing unregistered torrents never move. Native moves preserve seeding."""
    errors = []
    with transaction() as entries:
        for row in rows:
            record = next((entries.get(row.get(k)) for k in ('hash','infohash_v1','infohash_v2')
                           if entries.get(row.get(k))), None)
            if not record or record.get('published'):
                continue
            state = row.get('state', '')
            if (row.get('progress') != 1 or state not in {'uploading','stalledUP','forcedUP','stoppedUP','pausedUP','queuedUP'}
                    or row.get('share_limit_action') not in ('Stop', 'Remove')):
                continue
            current = str(row.get('save_path', '')).rstrip('/')
            if current == record['target']:
                # setLocation is asynchronous: acknowledge only on a later poll.
                record['published'] = True
                for key, value in entries.items():
                    if value['stage'] == record['stage']:
                        value['published'] = True
                try:
                    Path(record['stage']).rmdir()
                except OSError:
                    pass
                continue
            if current != record['stage']:
                errors.append('En torrent har skiftet placering; automatisk flytning er sat på pause.')
                continue
            try:
                target = Path(record['target'])
                # Never merge into another release, follow links, or overwrite files.
                for part in (target, *target.parents):
                    if part.is_symlink():
                        raise ValueError('Målmappen indeholder et link.')
                if target.exists() and any(target.iterdir()):
                    raise ValueError('Målmappen indeholder allerede filer; flytningen afventer kontrol.')
                target.mkdir(parents=True, exist_ok=True)
                api('torrents/setLocation', {'hashes':row['hash'], 'location':str(target)})
            except Exception:
                errors.append('En færdig download kunne ikke flyttes. Kontrollér lager og skriverettigheder.')
    return errors


def moving_progress(row, entries):
    """Best-effort estimate; qBittorrent does not expose native move progress."""
    if row.get('state') != 'moving':
        return {}
    unknown = {'move_progress': None}
    record = next((entries.get(row.get(k)) for k in ('hash','infohash_v1','infohash_v2')
                   if entries.get(row.get(k))), None)
    if not record or not row.get('size') or row['size'] <= 0:
        return unknown
    destination = Path(record['target'] if row.get('share_limit_action') in ('Stop','Remove') else record['stage'])
    if str(destination).rstrip('/') == str(row.get('save_path','')).rstrip('/'):
        return unknown
    try:
        if any(p.is_symlink() for p in (destination, *destination.parents)):
            return unknown
        if not destination.is_dir():
            return unknown
        allocated, count = 0, 0
        def failed(error):
            raise error
        for directory, dirs, files in os.walk(destination, followlinks=False, onerror=failed):
            dirs[:] = [d for d in dirs if not (Path(directory)/d).is_symlink()]
            for name in files:
                path = Path(directory)/name
                if path.is_symlink():
                    continue
                count += 1
                if count > 10000:
                    return unknown
                info = path.stat()
                if not hasattr(info, 'st_blocks'):
                    return unknown  # File length alone may be preallocated.
                allocated += min(info.st_size, info.st_blocks * 512)
        return {'move_progress': min(.99, allocated / row['size']), 'move_estimated': True}
    except OSError:
        return unknown
