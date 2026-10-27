"""Admission budget for RSS payloads; never stops existing torrents or edits feeds."""
from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time

from requests import RequestException

from state import atomic
from storage_browser import temporary_usage

_lock = threading.RLock()
MAX_BYTES = 2**53 - 1
GUARD_BYTES = 100 * 1024**3
SETTINGS = Path('/rpc/download-settings.json')


def read(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def validate(data):
    if not isinstance(data, dict):
        raise ValueError('Vælg en samlet lagergrænse eller slå grænsen fra.')
    limit = data.get('limit_bytes')
    if limit is not None and (type(limit) is not int or not 1 <= limit <= MAX_BYTES):
        raise ValueError('Lagergrænsen skal være større end nul. Brug GB eller TB.')
    return {'limit_bytes': limit}


@contextmanager
def admission_lock(root):
    # All feeds and the periodic status check share one process/file lock.
    # Hold it through reservation and add, including asynchronous add responses.
    with _lock, (root/'rss-budget.lock').open('a+') as handle:
        try:
            import fcntl
        except ImportError:
            fcntl = None
        if fcntl:
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(handle, fcntl.LOCK_UN)


def buffer_path(value, roots):
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return any(path.is_relative_to(root/name) for root in roots
               for name in ('.incomplete', '.fjordseed-buffer'))


def measure(api, roots, reservations):
    # Include all historical download locations and manual temporary downloads.
    # A missing/inaccessible mount is an error, never an empty buffer.
    for root in roots:
        if root.is_symlink() or not root.is_dir():
            raise ValueError('Downloadlageret kan ikke måles.')
    rows = api('torrents/info').json()
    # Sample remaining payload first. Downloads advancing during the disk walk
    # then overestimate commitments instead of admitting against stale usage.
    allocated = temporary_usage(roots)['temporary_bytes']
    live = {str(row.get(k) or '').lower() for row in rows
            for k in ('hash', 'infohash_v1', 'infohash_v2')} - {''}
    reservations = {key: value for key, value in reservations.items()
                    if not live.intersection(value['hashes'])}
    remaining = 0
    for row in rows:
        if not any(buffer_path(row.get(k), roots) for k in ('save_path', 'download_path', 'content_path')):
            continue
        left = row.get('amount_left')
        if (type(left) is not int or left < 0
                or row.get('state') in ('metaDL', 'forcedMetaDL')):
            raise ValueError('En igangværende downloads størrelse er ukendt.')
        remaining += left
    # Unobserved adds remain reserved after timeouts and restarts. Do not expire
    # them on a timer: the client may still accept an asynchronous add later.
    reserved = remaining + sum(r['size'] for r in reservations.values())
    return allocated, reserved, reservations


def status(api, root=Path('/config'), *, candidate=None, reserve=False):
    """Called under admission_lock. A candidate is checked again at final add."""
    config = validate(read(root/'fjord-rss-limit.json', {}))
    limit = config['limit_bytes']
    if limit is None:
        return {'limit_bytes': None, 'paused': False, 'reason': 'disabled'}
    state_path = root/'rss-budget-state.json'
    previous = read(state_path, {})
    reservations = previous.get('reservations', {})
    try:
        settings = read(SETTINGS, {})
        roots = [Path(p) for p in settings.get('buffer_roots', ['/downloads'])]
        allocated, reserved, reservations = measure(api, roots, reservations)
        committed = allocated + reserved
        paused = committed >= limit
        reason = 'limit' if paused else 'ready'
        fits = not paused
        if candidate is not None and not paused:
            size = candidate.get('size')
            if type(size) is not int or size <= 0:
                fits, reason = False, 'unknown_size'
            elif size > limit:
                fits, reason = False, 'too_large'
            elif committed + size > limit:
                fits, reason = False, 'candidate_space'
            elif reserve:
                hashes = [h.lower() for h in candidate['hashes']]
                reservations[hashes[0]] = {'hashes': hashes, 'size': size}
                reserved += size
                committed += size
        result = {'limit_bytes': limit, 'guard_bytes': GUARD_BYTES,
                  'near_limit': limit-committed <= GUARD_BYTES, 'temporary_bytes': allocated,
                  'reserved_bytes': reserved, 'committed_bytes': committed,
                  'available_bytes': max(0, limit-committed), 'paused': paused,
                  'reason': reason, 'fits': fits, 'checked_at': time.time()}
    except (OSError, ValueError, TypeError, KeyError, RequestException):
        result = {'limit_bytes': limit, 'guard_bytes': GUARD_BYTES, 'paused': True,
                  'fits': False, 'reason': 'measurement_error', 'checked_at': time.time()}
    atomic(state_path, json.dumps({**result, 'reservations': reservations}))
    return result


def release(root, hashes):
    path = root/'rss-budget-state.json'
    data = read(path, {})
    reservations = data.get('reservations', {})
    for key in list(reservations):
        if set(hashes).intersection(reservations[key]['hashes']):
            reservations.pop(key)
    atomic(path, json.dumps({**data, 'reservations': reservations}))


def public(root, config):
    limit = config['limit_bytes']
    if limit is None:
        return {'limit_bytes': None, 'paused': False, 'reason': 'disabled'}
    data = read(root/'qbit/rss-budget-state.json', {})
    if data.get('limit_bytes') != limit or not 0 <= time.time()-data.get('checked_at', 0) < 35:
        return {'limit_bytes': limit, 'guard_bytes': GUARD_BYTES, 'paused': True, 'reason': 'pending'}
    return {k: v for k, v in data.items() if k != 'reservations'}
