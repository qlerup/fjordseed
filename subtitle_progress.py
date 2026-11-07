"""Cross-container extraction telemetry; no subtitle text or credentials."""
import json
import re
import time
from pathlib import Path
from state import atomic


def telemetry(root, ident, **values):
    if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident):
        return
    root = Path(root)/'subtitle-work'
    root.mkdir(parents=True, exist_ok=True)
    atomic(root/(ident+'.progress.json'), json.dumps(dict(values, updated_at=time.time())))


def snapshot(root, ident):
    if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{32}', ident):
        return {}
    root = Path(root)/'subtitle-work'
    try:
        data = json.loads((root/(ident+'.progress.json')).read_text())
        if data.get('stage') == 'extract':
            path = root/(ident+'.ffmpeg')
            if path.exists():
                with path.open('rb') as stream:
                    stream.seek(max(0, path.stat().st_size-65536))
                    lines = stream.read().decode(errors='replace').splitlines()
                values = dict(line.split('=', 1) for line in lines if '=' in line)
                seconds = max(0, int(values.get('out_time_us', 0))/1000000)
                data['processed_seconds'] = round(seconds)
                if data.get('duration', 0) > 0:
                    data['fraction'] = min(.99, seconds/data['duration'])
        return data
    except (OSError, ValueError, TypeError):
        return {}


def present(job, root):
    result = dict(job)
    if result.get('state') == 'running' and result.get('stage') == 'extract':
        live = snapshot(root, result.get('progress_id'))
        if live:
            result.update(stage=live['stage'], stage_progress=live.get('fraction'))
            if live['stage'] == 'ocr':
                result['detail'] = f"Tekstgenkender PGS · {live.get('cues', 0)} undertekster læst"
                result['progress'] = 15+round(20*live.get('fraction', 0))
            else:
                result['detail'] = 'Udtrækker undertekst'
                if live.get('processed_seconds'):
                    result['detail'] += f" · {live['processed_seconds']} sekunder af filmen gennemgået"
                result['progress'] = round(15*live.get('fraction', 0))
    if result.get('started_at'):
        end = result.get('finished_at') or time.time()
        result['elapsed_seconds'] = max(0, int(end-result['started_at']))
    return result


def summary(jobs):
    if not jobs:
        return {'total': 0, 'progress': 0}
    latest = max(jobs, key=lambda j:j.get('created_at', 0))
    batches = {j.get('batch', j['job']) for j in jobs if j['state'] not in ('done', 'cancelled')}
    batches.add(latest.get('batch', latest['job']))
    current = [j for j in jobs if j.get('batch', j['job']) in batches]
    return {'total': len(current), 'done': sum(j['state']=='done' for j in current),
            'errors': sum(j['state']=='error' for j in current),
            'cancelled': sum(j['state']=='cancelled' for j in current),
            'running': sum(j['state']=='running' for j in current),
            'progress': sum(j.get('progress', 0) for j in current)//len(current)}
