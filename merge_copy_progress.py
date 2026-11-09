"""Measure existing copy operations without replacing their filesystem logic."""
from contextlib import contextmanager
import json
from pathlib import Path
import time

import download_storage as storage
from conversion import checked
from state import atomic


def progress_file(ident):
    return storage.CONFIG/'track-merges'/(ident+'.copy.json')


@contextmanager
def measure(ident, source, target, detail):
    path = progress_file(ident); path.parent.mkdir(parents=True, exist_ok=True)
    atomic(path, json.dumps({'active':True, 'target':str(target), 'total_bytes':checked(source).stat().st_size,
                            'started_at':time.time(), 'detail':detail}), mode=0o644)
    try: yield
    finally: atomic(path, json.dumps({'active':False}), mode=0o644)


def snapshot(ident, now=None):
    try:
        data = json.loads(progress_file(ident).read_text(encoding='utf-8'))
        if not data.get('active'): return {}
        total = data['total_bytes']
        if type(total) is not int or total<=0: return {}
        target = checked(Path(data['target']))
        copied = min(total, target.stat().st_size) if target.exists() else 0
        elapsed = max(0, (time.time() if now is None else now)-data['started_at'])
        eta = round((total-copied)/(copied/elapsed)) if elapsed>=3 and 0<copied<total else None
        return {'phase':'copying', 'detail':data['detail']+(' · færdiggør på disken' if copied==total else ''),
                'progress':round(min(99, copied/total*100),1), 'copied_bytes':copied, 'total_bytes':total,
                'eta_seconds':eta}
    except (OSError,ValueError,KeyError,TypeError): return {}
