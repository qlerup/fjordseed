"""Decaying estimates of additional physical upload, never replacement goals."""
import math

SEEDING_STATES = {'uploading', 'stalledUP', 'forcedUP'}
SMOOTHING_SECONDS = 10 * 60
FORECAST_SECONDS = 30 * 60
MIN_OBSERVATION_SECONDS = 2 * 60
MAX_SAMPLE_GAP = 2 * 60
MAX_IDLE_SECONDS = 15 * 60
MIN_UPLOAD_BYTES = 64 * 1024**2
MIN_RATIO_GAIN = .05


def valid_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def peer_count(value):
    return value if type(value) is int and value >= 0 else None


def upload_potential(entry, row, denominator, now):
    """One durable EWMA shared by worker and status polls, with bounded history.

    Only measured counter growth earns a forecast. Current speed, lifetime ratio
    or tracker demand alone cannot create one. Gaps, pauses and counter resets
    discard history rather than inventing progress while offline.
    """
    empty = {'seeding_upload_potential':False, 'seeding_predicted_upload':0,
             'seeding_predicted_ratio_gain':0, 'seeding_forecast_seconds':FORECAST_SECONDS}
    uploaded = row.get('uploaded')
    if (entry.get('adaptive_seeding') is not True or row.get('share_limit_action') != 'RemoveWithContent'
            or row.get('state') not in SEEDING_STATES
            or not valid_number(uploaded)):
        entry.pop('upload_potential', None)
        return empty
    previous = entry.get('upload_potential')
    if (previous is None or previous.get('basis')!='physical-upload-v1'
            or now < previous['at'] or now-previous['at'] > MAX_SAMPLE_GAP
            or uploaded < previous['uploaded']):
        previous = {'basis':'physical-upload-v1','at':now, 'since':now, 'uploaded':uploaded,
                    'rate':0, 'last_upload':None}
    elapsed = now-previous['at']
    if elapsed > 0:
        delta = uploaded-previous['uploaded']
        decay = math.exp(-elapsed/SMOOTHING_SECONDS)
        previous['rate'] = previous['rate']*decay + delta/elapsed*(1-decay)
        if delta > 0:
            previous['last_upload'] = now
        previous.update(at=now, uploaded=uploaded)
    entry['upload_potential'] = previous
    if (now-previous['since'] < MIN_OBSERVATION_SECONDS
            or previous['last_upload'] is None or now-previous['last_upload'] > MAX_IDLE_SECONDS
            or not valid_number(denominator) or not denominator):
        return empty
    leechers = peer_count(row.get('num_incomplete'))
    seeders = peer_count(row.get('num_complete'))
    # Unknown tracker counts use measured upload only. Known low demand lowers
    # throughput and caps the amount that could plausibly be requested.
    competition = leechers/(seeders+1) if leechers is not None and seeders is not None else None
    predicted = previous['rate']*FORECAST_SECONDS
    if competition is not None:
        predicted = min(predicted*min(1,competition), denominator*competition)
    elif leechers == 0:
        predicted = 0
    gain = predicted/denominator
    return {'seeding_upload_potential':predicted >= max(MIN_UPLOAD_BYTES,denominator*MIN_RATIO_GAIN),
            'seeding_predicted_upload':predicted, 'seeding_predicted_ratio_gain':gain,
            'seeding_forecast_seconds':FORECAST_SECONDS}
