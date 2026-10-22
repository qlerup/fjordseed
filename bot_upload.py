"""Public, read-only upload choices; never expose tracker credentials."""
import math
import time


def amount(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def upload_choices(rss, trackers, now=None):
    now = time.time() if now is None else now
    choices = []
    for feed in rss.public().get('feeds', [])[:20]:
        choices.append({'kind': 'rss', 'id': feed['id'], 'name': feed['name'],
                        'credited_uploaded': amount(feed.get('credited_uploaded')),
                        'estimated': bool(feed.get('credit_estimated')),
                        'updated_at': None})
    for tracker in trackers.public().get('trackers', [])[:10]:
        updated = amount(tracker.get('updated_at'))
        fresh = tracker.get('status') == 'ok' and updated is not None and 0 <= now - updated < 600
        choices.append({'kind': 'tracker', 'id': tracker['id'], 'name': tracker['name'],
                        'credited_uploaded': amount(tracker.get('stats', {}).get('uploaded')) if fresh else None,
                        'estimated': False, 'updated_at': updated if fresh else None})
    return {'ok': True, 'options': choices}
