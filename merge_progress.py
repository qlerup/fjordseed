"""Read bounded FFmpeg telemetry without importing media decoding libraries."""
import json
import math
import time


def number(value):
    try: value = float(value)
    except (TypeError, ValueError, OverflowError): return None
    return value if math.isfinite(value) else None


def snapshot(directory, now=None):
    now = time.time() if now is None else now
    try:
        data = json.loads((directory/'progress.json').read_text(encoding='utf-8'))
        result = {key: data[key] for key in ('detail', 'progress', 'stage', 'stage_index', 'stage_total', 'duration', 'updated_at') if key in data}
        start = number(data.get('stage_started_at'))
        if start is not None: result['stage_elapsed_seconds'] = max(0, int(now-start))
        name = data.get('progress_file')
        if name not in ('video.ffmpeg', 'audio.ffmpeg'): return result
        result['eta_seconds'] = None
        path = directory/name
        if path.exists():
            with path.open('rb') as handle:
                handle.seek(max(0, path.stat().st_size-65536))
                lines = handle.read().decode(errors='replace').splitlines()
            current = {}; latest = {}
            for line in lines:
                if '=' not in line: continue
                key, value = line.split('=', 1); current[key] = value
                if key == 'progress': latest = current; current = {}
            raw = number(latest.get('out_time_us'))
            duration = number(data.get('duration'))
            if raw is not None and duration is not None and duration > 0:
                seconds = min(duration, max(0, raw/1e6))
                ended = latest.get('progress') == 'end'
                result.update(processed_seconds=round(seconds, 3),
                              progress=100 if ended else round(min(99., seconds/duration*100), 1),
                              updated_at=path.stat().st_mtime)
                speed = number(latest.get('speed', '').removesuffix('x'))
                fresh = now-result['updated_at'] <= 15
                if (fresh and not ended and seconds < duration and start is not None and now-start >= 3
                        and seconds >= min(2., duration*.1) and speed is not None and speed > 0):
                    result['eta_seconds'] = round((duration-seconds)/speed)
                if seconds >= duration and not ended:
                    result['detail'] = 'Færdiggør videofilen' if data.get('stage') == 'video' else 'Færdiggør lydprøven'
        updated = number(result.get('updated_at'))
        result['stale'] = updated is not None and now-updated > 15
        if result['stale']: result['eta_seconds'] = None
        return result
    except (OSError, ValueError, TypeError, AttributeError):
        return {}
