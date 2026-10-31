"""Durable receipts for automatic deletions, confirmed on a later worker poll."""
import hashlib
import json
import logging
import math
import os
import stat
from pathlib import Path

from state import atomic

LOG = logging.getLogger(__name__)


def directory():
    from download_storage import CONFIG
    return CONFIG / 'auto-delete-events'


def releasable_bytes(content):
    """Allocated file blocks, excluding inodes with links outside the deleted tree.

    This is an estimate: filesystem snapshots/reflinks and open files can retain
    blocks after unlink. An unreadable/missing source is unknown, never zero.
    """
    if not isinstance(content, str) or not content:
        return None
    seen = {}
    def collect(info):
        if not stat.S_ISREG(info.st_mode):
            return
        identity = (info.st_dev, info.st_ino)
        if identity not in seen:
            seen[identity] = [info.st_blocks * 512, info.st_nlink, 0]
        seen[identity][2] += 1
    try:
        source = Path(content)
        if any(part.is_symlink() for part in (source, *source.parents)):
            return None
        info = source.stat()
        if stat.S_ISREG(info.st_mode):
            collect(info)
        elif stat.S_ISDIR(info.st_mode):
            def fail(error):
                raise error
            for _, _, files, fd in os.fwalk(source, follow_symlinks=False, onerror=fail):
                for name in files:
                    collect(os.stat(name, dir_fd=fd, follow_symlinks=False))
        else:
            return None
        return sum(size for size, links, found in seen.values() if found == links)
    except (OSError, ValueError, AttributeError):
        return None


def delete_completed(api, row, credit, *, converted=False):
    from green_credit import real_ratio
    target = 1 if converted else credit['ratio_limit']
    from qbit_rpc import SEEDING_MINUTES
    hours = SEEDING_MINUTES // 60 + (0 if converted else credit.get('extra_seed_hours', 0))
    timed = credit.get('seed_minutes') if not converted else None
    if timed:
        hours = timed / 60
    identity = str(row['hash']) + ':' + str(row.get('added_on', 0))
    event_id = 'deleted-' + hashlib.sha256(identity.encode()).hexdigest()
    path = directory() / (event_id + '.json')
    event = {'type': 'download_deleted', 'event_id': event_id,
             'filename': str(row.get('name') or 'Ukendt fil')[:200],
             'reason': 'time' if timed else 'ratio' if real_ratio(credit) >= target else 'time',
             'ratio_limit': target, 'seed_hours': hours, 'library_retained': converted}
    content = row.get('content_path')
    event['freed_bytes'] = releasable_bytes(content)
    # Preserve the durable ledger totals, not resettable client counters or
    # the configured ratio target. Unknown data must not look like zero upload.
    event['transfer'] = {
        field: value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
        for field in ('uploaded', 'credited_uploaded', 'ratio')
        for value in (credit.get(field),)
    }
    # qBittorrent supplies this path; never send it to the Hub or Matrix.
    receipt = {'hash': row['hash'], 'content_path': content if isinstance(content, str) else '',
               'ready': False, 'event': event}
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic(path, json.dumps(receipt), mode=0o644)
    try:
        api('torrents/delete', {'hashes': row['hash'], 'deleteFiles': 'true'})
    except Exception:
        path.unlink(missing_ok=True)
        raise
    # A successful API response accepts an asynchronous operation. Confirm it
    # on a fresh snapshot, including removal of the original content, before notifying.
    return True


def confirm_deletions(rows):
    active = {row.get('hash') for row in rows}
    for path in directory().glob('deleted-*.json'):
        try:
            receipt = json.loads(path.read_text())
            if receipt['ready'] or receipt['hash'] in active:
                continue
            content = receipt.get('content_path')
            if not content:
                # No trustworthy file location: do not claim confirmed file deletion.
                continue
            source = Path(content)
            if source.is_symlink() or source.is_file():
                continue
            if source.exists():
                def fail(error):
                    raise error
                if any(files for _, _, files in os.walk(source, followlinks=False, onerror=fail)):
                    continue
            receipt['ready'] = True
            atomic(path, json.dumps(receipt), mode=0o644)
        except FileNotFoundError:
            continue  # Sender may have acknowledged a ready receipt.
        except (OSError, ValueError, KeyError, TypeError):
            LOG.exception('Could not confirm automatic deletion receipt')
