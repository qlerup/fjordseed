"""Persistent, conservative Green upload accounting shared by RPC and worker."""
from contextlib import contextmanager
from datetime import datetime
import json
import math
from pathlib import Path
import threading
import time

from state import atomic

CONFIG = Path('/config')
POLICIES = Path('/rpc/green-policy.json')
GREEN_SECONDS = 24 * 3600 + 30 * 60
_lock = threading.RLock()


def created_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        stamp = date.timestamp()
        return stamp if date.tzinfo is not None and math.isfinite(stamp) and stamp > 0 else None
    except (ValueError, OverflowError, OSError):
        return None


def policy_from_result(result):
    dates = [created_timestamp(m.get('created_at')) for m in result.get('matches', [])
             if m.get('tracker_provider') == 'nordicbytes' and not m.get('own_upload')]
    dates = [date for date in dates if date is not None]
    return {'until': max(dates) + GREEN_SECONDS if dates else None,
            'known': result.get('status') != 'pending' and all('created_at' in m for m in result.get('matches', [])),
            'has_date': bool(dates) or any(m.get('own_upload') for m in result.get('matches', []))}


def read(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def green_safety_factor():
    return 2 if read(POLICIES, {}).get('_enabled') else 1


def initial_ratio_limit(hashes, target, now=None):
    """Shared manual/RSS startup policy before any payload can download."""
    now=time.time() if now is None else now
    with CreditLedger().transaction() as ledger:
        ledger.register(hashes,target)
        policies=[ledger.policies.get(h,ledger.entries[h]['policy']) for h in hashes]
        pending=ledger.policies.get('_enabled',False) and (
            not policies or any(not p.get('known') or p.get('has_date') is False for p in policies))
        green=any(number(p.get('until'))>now for p in policies)
    return target * (2 if green or pending else 1)


def number(value):
    return max(0, value) if type(value) in (int, float) and math.isfinite(value) else 0


class CreditLedger:
    @contextmanager
    def transaction(self):
        CONFIG.mkdir(parents=True, exist_ok=True)
        with _lock, (CONFIG / 'green-credit.lock').open('a+') as handle:
            # All production writers are Linux processes. The thread lock also
            # makes Windows development/tests deterministic.
            try:
                import fcntl
            except ImportError:
                fcntl = None
            if fcntl:
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                self.entries = read(CONFIG / 'green-credit.json', {})
                self.policies = read(POLICIES, {})
                self.feeds = read(CONFIG / 'fjord-rss.json', [])
                yield self
                atomic(CONFIG / 'green-credit.json', json.dumps(self.entries))
            finally:
                if fcntl:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def register(self, hashes, target, policy=None):
        for ident in hashes:
            if ident not in self.entries:
                self.entries[ident] = {'target': max(1, target), 'uploaded': 0,
                    'green_uploaded': 0, 'at': time.time(), 'policy': policy or {'known': not self.policies.get('_enabled', False), 'until': None}}

    def update(self, row, target=None, now=None):
        now = time.time() if now is None else now
        ident = row['hash'].lower()
        uploaded = number(row.get('uploaded'))
        entry = self.entries.get(ident)
        if entry is None or (entry.get('added_on') and row.get('added_on') and entry['added_on'] != row['added_on']):
            tags={tag.strip() for tag in str(row.get('tags','')).split(',')}
            feed = next((f for f in self.feeds if 'FjordSeed-RSS-' + f['id'] in tags), None)
            # Imports retain their actual per-torrent goal, including manual
            # edits. Only fresh native RSS additions inherit the feed goal.
            fresh_feed=feed if number(row.get('added_on'))>=self.policies.get('_started_at',float('inf')) else None
            entry = {'target': max(1, number((fresh_feed or {}).get('ratio_limit', row.get('ratio_limit')))),
                     'uploaded': 0, 'green_uploaded': 0, 'at': number(row.get('added_on')) or now,
                     'policy': {'known': not self.policies.get('_enabled', False), 'until': None}}
            self.entries[ident] = entry
        if target is not None:
            entry['target'] = target
        entry['added_on'] = row.get('added_on')
        policy = self.policies.get(ident, entry['policy'])
        entry['policy'] = policy
        pending = not policy.get('known') or bool(self.policies.get('_enabled') and policy.get('has_date') is False)
        until = number(policy.get('until'))
        delta = max(0, uploaded - entry['uploaded'])
        # An interval crossing expiry is charged at half in full: at most one
        # polling interval of conservative over-seeding, never invented credit.
        # Newly discovered historic torrents are likewise treated conservatively.
        green = bool(until and (entry['at'] < until or not entry.get('classified')))
        if green and (not row.get('added_on') or row['added_on'] < until):
            entry['green_uploaded'] += delta
            if not entry.get('classified') and now >= until and delta:
                entry['history_estimated'] = True
        elif pending:
            entry['unclassified'] = entry.get('unclassified', 0) + delta
        if until and entry.get('unclassified') and (not row.get('added_on') or row['added_on'] < until):
            entry['green_uploaded'] += entry.pop('unclassified')
            if now >= until:
                entry['history_estimated'] = True
        elif not pending:
            entry.pop('unclassified', None)
        entry.update(uploaded=uploaded, at=now, classified=not pending)
        # Never let a counter reset create negative or unearned credit.
        discounted = min(uploaded, entry['green_uploaded'] + (entry.get('unclassified', 0) if pending else 0))
        credited = uploaded - discounted / 2
        denominator = number(row.get('downloaded'))
        if not denominator and number(row.get('ratio')):
            denominator = uploaded / row['ratio']
        active = until > now
        native = entry['target'] * 2 if active or pending else entry['target'] + (discounted / 2 / denominator if denominator else 0)
        raw_ratio = number(row.get('ratio'))
        return {'ratio_limit': entry['target'], 'native_ratio_limit': native,
                'credited_ratio': credited / denominator if denominator else raw_ratio / (2 if active or pending else 1),
                'credited_uploaded': credited, 'green_uploaded': discounted,
                'green_until': until or None, 'green_active': active, 'green_pending': pending,
                'green_date_unavailable': bool(self.policies.get('_enabled') and policy.get('known')
                    and not until and policy.get('has_date') is False),
                'green_history_estimated': entry.get('history_estimated', False)}
