"""Persistent, conservative Green upload accounting shared by RPC and worker."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path
import re
import threading
import time

from state import atomic
from tracker_providers import PROVIDERS
from seed_potential import upload_potential

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
             if m.get('tracker_provider') in PROVIDERS and not m.get('own_upload')]
    dates = [date for date in dates if date is not None]
    matches=result.get('matches',[])
    free=[m.get('freeleech') for m in matches]
    verified_free=(free[0] if result.get('status')=='matched' and free
        and all(type(v) in (int,float) and v in (0,25,50,75,100) and v==free[0] for v in free) else None)
    download_policy=({'download_freeleech':verified_free,'benefits_checked_at':result.get('checked_at')} if verified_free is not None else {})
    return {**download_policy,'until': max(dates) + GREEN_SECONDS if dates else None,
            'known': result.get('status') != 'pending' and all('created_at' in m for m in result.get('matches', [])),
            'has_date': bool(dates) or any(m.get('own_upload') for m in result.get('matches', []))}


def read(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default


def initial_ratio_limit(hashes, target, now=None, ratio_only=False, adaptive=False, stop_on_complete=False):
    """Shared manual/RSS startup policy before any payload can download."""
    with CreditLedger().transaction() as ledger:
        ledger.register(hashes,target,ratio_only=ratio_only,adaptive=adaptive,stop_on_complete=stop_on_complete)
    return target


def number(value):
    return max(0, value) if type(value) in (int, float) and math.isfinite(value) else 0


def real_ratio(row):
    """Physical torrent traffic; tracker account credit never affects seeding."""
    uploaded,downloaded=row.get('uploaded'),row.get('downloaded')
    if (type(uploaded) in (int,float) and math.isfinite(uploaded) and uploaded>=0
            and type(downloaded) in (int,float) and math.isfinite(downloaded) and downloaded>0):
        return uploaded/downloaded
    return number(row.get('ratio'))


def physical_traffic(entry, row):
    """Accumulate observed traffic even if qBittorrent restores an old checkpoint.

    A falling native counter establishes a new baseline, never new traffic.
    Legacy Green buckets contain already observed bytes and can recover a
    higher historical upload total without consulting tracker account credit.
    """
    totals=entry.get('physical_traffic')
    valid_upload=type(row.get('uploaded')) in (int,float) and math.isfinite(row['uploaded']) and row['uploaded']>=0
    valid_download=type(row.get('downloaded')) in (int,float) and math.isfinite(row['downloaded']) and row['downloaded']>=0
    uploaded=number(row['uploaded']) if valid_upload else number((totals or {}).get('last_uploaded',entry.get('uploaded')))
    downloaded=number(row['downloaded']) if valid_download else number((totals or {}).get('last_downloaded'))
    if totals is None:
        previous=number(entry.get('uploaded'))
        delta=max(0,uploaded-previous)
        observed=max(previous,number(entry.get('green_uploaded'))+number(entry.get('unclassified')))
        totals={'uploaded':max(uploaded,observed+delta),'downloaded':downloaded,
                'rolled_back':uploaded<observed}
        reset=uploaded<observed
    else:
        reset=uploaded<totals['last_uploaded'] or downloaded<totals['last_downloaded']
        delta=max(0,uploaded-totals['last_uploaded'])
        totals['uploaded']+=delta
        totals['downloaded']+=max(0,downloaded-totals['last_downloaded'])
        totals['rolled_back']=totals.get('rolled_back',False) or reset
    totals.update(last_uploaded=uploaded,last_downloaded=downloaded)
    entry['physical_traffic']=totals
    return totals,delta,reset or not valid_upload


def seed_time(entry, row):
    """Exclude native counter growth during moves and pauses, including transitions."""
    raw = row.get('seeding_time')
    if type(raw) not in (int, float) or not math.isfinite(raw) or raw < 0:
        return entry.get('seed_clock', {}).get('seconds', 0)
    moving = row.get('state') == 'moving'
    paused = row.get('state') in ('pausedUP', 'pausedDL', 'stoppedUP', 'stoppedDL')
    clock = entry.get('seed_clock')
    if clock is None:
        clock = {'seconds': raw}
    elif not moving and not paused and not clock['moving'] and not clock.get('paused', False):
        clock['seconds'] += max(0, raw - clock['raw'])
    clock.update(raw=raw, moving=moving, paused=paused)
    entry['seed_clock'] = clock
    return clock['seconds']


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
                self.tracker_policies=read(POLICIES.with_name('tracker-credit.json'),{})
                self.feeds = read(CONFIG / 'fjord-rss.json', [])
                self.reconcile_tracker_archives()
                yield self
                self.save()
            finally:
                if fcntl:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def save(self):
        """Persist goals before disabling qBittorrent's native stop limits."""
        atomic(CONFIG / 'green-credit.json', json.dumps(self.entries))

    def reconcile_tracker_archives(self):
        if self.tracker_policies.get('_version')!=1:return
        from tracker_credit import accrue
        now=time.time()
        for feed in self.entries.get('_rss_upload',{}).get('feeds',{}).values():
            if feed.get('migrated_to'):continue
            for ident,item in feed.get('downloads',{}).items():
                state=item.get('tracker_accounting')
                if ident in self.entries or not state or not state.get('pending'):continue
                up,down=accrue(state,0,0,state.get('at',now),now,self.tracker_policies.get(ident,{}))
                feed['credited_uploaded']+=up;item['credited_uploaded']+=up
                item['credited_downloaded']=number(item.get('credited_downloaded'))+down
                item['upload_credit_pending']=sum(s['uploaded'] for s in state['pending'])
                item['download_credit_pending']=sum(s['downloaded'] for s in state['pending'])
                item['upload_credit_incomplete']=bool(state.get('unknown_uploaded') or state.get('legacy_upload_incomplete'))
                item['download_credit_incomplete']=bool(state.get('unknown_downloaded') or state.get('legacy_download_incomplete'))
                item['tracker_credit_estimated']=bool(state.get('estimated') or state.get('legacy_credit'))

    def register(self, hashes, target, policy=None, ratio_only=False, adaptive=False, stop_on_complete=False):
        for ident in hashes:
            if ident not in self.entries:
                self.entries[ident] = {'target': max(1, target), 'ratio_only': ratio_only, 'adaptive_seeding':adaptive, 'stop_on_complete':stop_on_complete, 'uploaded': 0,
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
                     'ratio_only': (fresh_feed or {}).get('ratio_action') == 'delete_ratio',
                     'adaptive_seeding': (fresh_feed or {}).get('ratio_action') == 'automatic',
                     'stop_on_complete': (fresh_feed or {}).get('ratio_action') == 'stop_keep',
                     'uploaded': 0, 'green_uploaded': 0, 'at': number(row.get('added_on')) or now,
                     'policy': {'known': not self.policies.get('_enabled', False), 'until': None}}
            self.entries[ident] = entry
        if target is not None:
            entry['target'] = target
        traffic,delta,reset=physical_traffic(entry,row)
        if reset:entry.pop('upload_potential',None)
        entry['added_on'] = row.get('added_on')
        policy = self.policies.get(ident, entry['policy'])
        entry['policy'] = policy
        pending = not policy.get('known') or bool(self.policies.get('_enabled') and policy.get('has_date') is False)
        until = number(policy.get('until'))
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
        entry.update(uploaded=traffic['last_uploaded'], at=now, classified=not pending)
        uploaded=traffic['uploaded']
        # Never let a counter reset create negative or unearned credit.
        discounted = min(uploaded, entry['green_uploaded'] + (entry.get('unclassified', 0) if pending else 0))
        credited = uploaded - discounted / 2
        self.record_rss_upload(row, entry, credited, now, pending)
        denominator = traffic['downloaded']
        if not denominator and number(row.get('ratio')):
            denominator = uploaded / row['ratio']
        active = until > now
        display_credit=entry.get('tracker_credited_uploaded',credited)
        tracker_rules=self.tracker_policies.get(ident,{}) if entry.get('tracker_accounting') else {}
        display_until=tracker_rules.get('green_until',until)
        display_until=display_until if type(display_until) in (int,float) else until
        raw_ratio = number(row.get('ratio'))
        return {'seeding_time': seed_time(entry, row), 'extra_seed_hours': entry.get('extra_seed_hours', 0),
                'ratio_only': entry.get('ratio_only', False),
                'adaptive_seeding': entry.get('adaptive_seeding', False),
                'stop_on_complete': entry.get('stop_on_complete', False),
                'uploaded':uploaded,'downloaded':traffic['downloaded'],
                'client_uploaded':traffic['last_uploaded'],'client_downloaded':traffic['last_downloaded'],
                'traffic_counter_rollback':traffic.get('rolled_back',False),
                'ratio':real_ratio({**row,'uploaded':uploaded,'downloaded':traffic['downloaded']}),
                'ratio_limit': entry['target'], 'native_ratio_limit':entry['target'],
                'credited_ratio': credited / denominator if denominator else raw_ratio / (2 if active or pending else 1),
                'credited_uploaded': display_credit, 'green_uploaded': discounted,
                'tracker_double_upload':tracker_rules.get('double_upload'),
                'green_until': display_until or None, 'green_active': display_until>now, 'green_pending': pending,
                'green_date_unavailable': bool(self.policies.get('_enabled') and policy.get('known')
                    and not until and policy.get('has_date') is False),
                'green_history_estimated': entry.get('history_estimated', False),
                **upload_potential(entry,{**row,'uploaded':uploaded},denominator,now)}

    def record_rss_title(self, feed_id, ident, title, now=None):
        """Archive text independently of the live torrent/sample lifecycle."""
        now = time.time() if now is None else now
        history = self.entries.setdefault('_rss_upload', {'started_at': now, 'feeds': {}})
        total = history['feeds'].setdefault(feed_id, {'credited_uploaded': 0, 'estimated': False})
        item = total.setdefault('downloads', {}).setdefault(ident.lower(), {
            'title': 'Ukendt titel', 'added_at': now, 'credited_uploaded': 0, 'estimated': False})
        if isinstance(title, str) and title.strip():
            item['title'] = title.strip()[:1000]
        return item

    def record_rss_upload(self, row, entry, credited, now, pending):
        """Keep feed totals in the same atomic ledger as per-torrent samples.

        Removing a torrent may retire its goal/sample, but never its feed total.
        Repeated status/worker polls replace that torrent's previous contribution.
        """
        history = self.entries.setdefault('_rss_upload', {'started_at': now, 'feeds': {}})
        feed_id = entry.get('rss_feed_id')
        if not feed_id:
            tags = str(row.get('tags', '')).split(',')
            feed_ids = {tag.strip()[len('FjordSeed-RSS-'):] for tag in tags
                        if re.fullmatch(r'FjordSeed-RSS-[a-f0-9]{32}', tag.strip())}
            if len(feed_ids) != 1:
                return
            feed_id = entry['rss_feed_id'] = feed_ids.pop()
        total = history['feeds'].setdefault(feed_id, {'credited_uploaded': 0, 'estimated': False})
        previous_credit = number(entry.get('rss_credited_uploaded'))
        live_accounting=self.tracker_policies.get('_version')==1
        if not live_accounting:total['credited_uploaded'] = max(0, total['credited_uploaded'] + credited - previous_credit)
        total['estimated'] = total['estimated'] or pending or entry.get('history_estimated', False)
        item = self.record_rss_title(feed_id, row['hash'], row.get('name'), now)
        # When upgrading an existing sample, its old contribution is already in
        # the feed total, but the new per-title archive needs the full credit.
        item_previous = previous_credit if entry.get('rss_title_recorded') else 0
        if not live_accounting:item['credited_uploaded'] = max(0, item['credited_uploaded'] + credited - item_previous)
        item['estimated'] = item['estimated'] or pending or bool(entry.get('history_estimated'))
        traffic=entry.get('physical_traffic',{})
        previous=entry.setdefault('rss_traffic_sample',{})
        first_sample=not previous
        if live_accounting:
            from tracker_credit import accrue
            rules=self.tracker_policies.get(row['hash'].lower(),{})
            state=entry.get('tracker_accounting')
            if state is None:
                state={**deepcopy(item.get('tracker_accounting',{})),
                       'at':(number(item.get('traffic_updated_at')) or now-1) if previous else number(row.get('added_on')) or now,
                       'legacy_credit':item.get('credited_uploaded',0)>0,
                       'legacy_upload_incomplete':item.get('upload_credit_incomplete',False),
                       'legacy_download_incomplete':item.get('download_credit_incomplete',False),
                       'unknown_downloaded':number(previous.get('downloaded')) if item.get('download_credit_incomplete') else 0}
                entry['tracker_accounting']=state
            delta_up=max(0,number(traffic.get('uploaded'))-number(previous.get('uploaded')))
            delta_down=max(0,number(traffic.get('downloaded'))-number(previous.get('downloaded')))
            if first_sample and number(row.get('added_on'))<now-30:
                state['unknown_uploaded']=state.get('unknown_uploaded',0)+delta_up
                state['unknown_downloaded']=state.get('unknown_downloaded',0)+delta_down
                delta_up=delta_down=0
            extra_up,extra_down=accrue(state,delta_up,delta_down,state['at'],now,rules)
            state['at']=now
            total['credited_uploaded']+=extra_up
            item['credited_uploaded']+=extra_up
            item['credited_downloaded']=number(item.get('credited_downloaded'))+extra_down
            item['upload_credit_pending']=sum(s['uploaded'] for s in state['pending'])
            item['download_credit_pending']=sum(s['downloaded'] for s in state['pending'])
            item['upload_credit_incomplete']=bool(state.get('unknown_uploaded') or state.get('legacy_upload_incomplete'))
            item['download_credit_incomplete']=bool(state.get('unknown_downloaded') or state.get('legacy_download_incomplete'))
            item['tracker_credit_estimated']=bool(state.get('estimated') or state.get('legacy_credit'))
            item['tracker_flags']={'green_until':rules.get('green_until'),'double_upload':rules.get('double_upload'),
                'freeleech':rules.get('freeleech'),'checked_at':rules.get('checked_at')}
            item['tracker_accounting']=state
            entry['tracker_credited_uploaded']=item['credited_uploaded']
        for field in ('uploaded','downloaded'):
            if type(row.get(field)) not in (int,float):continue
            total=number(traffic.get(field))
            delta=max(0,total-number(previous.get(field)))
            item[field]=number(item.get(field))+delta
            if field=='downloaded' and delta and not live_accounting:
                rate=entry.get('policy',{}).get('download_freeleech')
                checked=entry.get('policy',{}).get('benefits_checked_at')
                valid=(type(rate) in (int,float) and rate in (0,25,50,75,100)
                    and type(checked) in (int,float) and 0<=now-checked<=600)
                # Previously downloaded bytes have no historical badge timeline.
                # Keep that uncertainty permanently instead of applying today's
                # freeleech percentage retrospectively to the entire download.
                historic=first_sample and number(row.get('added_on'))<now-30
                if valid and not historic:
                    item['credited_downloaded']=number(item.get('credited_downloaded'))+delta*(1-rate/100)
                else:item['download_credit_incomplete']=True
            previous[field]=total
        item['traffic_updated_at']=now
        if type(row.get('size')) in (int,float):item['size']=number(row['size'])
        if type(row.get('progress')) in (int,float):item['progress']=max(0,min(1,row['progress']))
        if row.get('completion_on'):item['completed_at']=row['completion_on']
        entry['rss_title_recorded'] = True
        entry['rss_credited_uploaded'] = credited
