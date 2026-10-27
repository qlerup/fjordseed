"""Allowlisted qBittorrent RPC executed inside the VPN network namespace."""
import base64
import io
import json
import math
from pathlib import Path
import re
import sys

import requests
from green_credit import CreditLedger, initial_ratio_limit, real_ratio

BASE = 'http://127.0.0.1:8080/api/v2/'
SEEDING_BASE_HOURS = 48
SEEDING_BUFFER_HOURS = 1
SEEDING_MINUTES = (SEEDING_BASE_HOURS + SEEDING_BUFFER_HOURS) * 60
SEEDING_SECONDS = SEEDING_MINUTES * 60
MAX_ACTIVE_DOWNLOADS = 8
DOWNLOAD_QUEUE_PREFERENCES = {
    'queueing_enabled': True,
    'max_active_downloads': MAX_ACTIVE_DOWNLOADS,
    'max_active_uploads': -1,
    'max_active_torrents': -1,
    'dont_count_slow_torrents': False,
}
ACTIVE_DOWNLOAD_STATES={'downloading','stalledDL','forcedDL','metaDL','forcedMetaDL'}
WAITING_DOWNLOAD_STATES={'queuedDL'}


def rss_download(row):
    return any(tag.strip().startswith('FjordSeed-RSS-') for tag in str(row.get('tags','')).split(','))


def download_queue_summary(rows):
    active=[r for r in rows if r.get('state') in ACTIVE_DOWNLOAD_STATES]
    waiting=[r for r in rows if r.get('state') in WAITING_DOWNLOAD_STATES]
    return {'active':len(active),'limit':MAX_ACTIVE_DOWNLOADS,'waiting':len(waiting),
            'rss_active':sum(rss_download(r) for r in active),'manual_active':sum(not rss_download(r) for r in active)}


def prioritize_rss_downloads(api,rows):
    """Stable RSS-first native queue; never start paused torrents or force downloads."""
    eligible=[r for r in rows if r.get('state') in ACTIVE_DOWNLOAD_STATES|WAITING_DOWNLOAD_STATES
              and type(r.get('priority')) is int and r['priority']>=0]
    ordered=sorted(eligible,key=lambda r:r['priority'])
    rss=[r for r in ordered if rss_download(r)]
    manual=[r for r in ordered if not rss_download(r)]
    if rss and manual and rss[-1]['priority']>manual[0]['priority']:
        # Move individually in reverse order: preserves order within RSS.
        for row in reversed(rss):
            api('torrents/topPrio',{'hashes':row['hash']})


def sync_download_queue(prefs=None, api=None):
    """Use one native queue for manual, gated RSS and native RSS downloads."""
    api = api or call
    if prefs is None:
        prefs = api('app/preferences').json()
    if any(prefs.get(key) != value for key, value in DOWNLOAD_QUEUE_PREFERENCES.items()):
        api('app/setPreferences', {'json': json.dumps(DOWNLOAD_QUEUE_PREFERENCES)})
        updated = api('app/preferences').json()
        if any(updated.get(key) != value for key, value in DOWNLOAD_QUEUE_PREFERENCES.items()):
            raise RuntimeError('Download queue settings were not applied')


def normalize_forced_downloads(api, rows):
    # Force-started incomplete torrents bypass qBittorrent's queue. Completed
    # seeders and manually stopped torrents must retain their existing state.
    hashes = [row['hash'] for row in rows if row.get('state') in ('forcedDL', 'forcedMetaDL')]
    if hashes:
        api('torrents/setForceStart', {'hashes': '|'.join(hashes), 'value': 'false'})


class SeedingRequirementError(ValueError):
    pass


def seed_ratio(value):
    try:
        ratio=float(value)
    except (ValueError,TypeError):
        return 1.0
    return max(1.0,ratio) if math.isfinite(ratio) else 1.0


def stop_requirement(row):
    target=1.0
    ratio=real_ratio(row)
    seconds=row.get('seeding_time')
    ratio_done=type(ratio) in (int,float) and math.isfinite(ratio) and ratio>=target
    time_done=type(seconds) in (int,float) and math.isfinite(seconds) and seconds>=SEEDING_SECONDS
    allowed=bool(ratio_done or time_done)
    return {'seeding_requirement_met':allowed,'required_seeding_seconds':SEEDING_SECONDS,
            'stop_reason':'' if allowed else 'Torrenten har endnu ikke opfyldt kravet om ratio 1:1 eller 49 timers seeding. Hvis du stopper eller fjerner den nu, kan trackeren registrere det som hit-and-run.'}


def sync_share_limits(api=None):
    api=api or call
    with CreditLedger().transaction() as ledger:
        rows=api('torrents/info').json()
        from deletion_events import confirm_deletions
        confirm_deletions(rows)
        normalize_forced_downloads(api, rows)
        prioritize_rss_downloads(api,rows)
        credits=[ledger.update(row) for row in rows]
        ledger.save()
        # Stop before publishing can start an asynchronous file move.
        from download_storage import read as storage_read, CONFIG as storage_config
        storage_records=storage_read(storage_config/'download-storage.json',{})
        for row,credit in zip(rows,credits):
            converting=any(storage_records.get(row.get(k),{}).get('convert') for k in ('hash','infohash_v1','infohash_v2'))
            if credit.get('stop_on_complete') and not converting:
                finish_seeding(api,row,credit)
        from download_storage import publish_complete
        storage_errors = publish_complete(api, rows)
        from library_conversion import reconcile as reconcile_library
        storage_errors += reconcile_library(api, rows)
        for row,credit in zip(rows,credits):
            apply_limits(api,row)
            converting=any(storage_records.get(row.get(k),{}).get('convert') for k in ('hash','infohash_v1','infohash_v2'))
            if (not credit.get('stop_on_complete') or converting) and finish_seeding(api,row,credit):
                from download_storage import forget
                forget([row.get(k) for k in ('hash','infohash_v1','infohash_v2')])
                for key in ('hash','infohash_v1','infohash_v2'):
                    ledger.entries.pop(str(row.get(key) or '').lower(),None)
        return storage_errors


def apply_limits(api,row,action=None):
    # Native limits can fire between polls and disconnect active downloaders.
    # The durable ledger owns the goal; qBittorrent retains the file action.
    if (row.get('ratio_limit')!=-1 or row.get('seeding_time_limit')!=-1
            or row.get('inactive_seeding_time_limit')!=-1
            or (action is not None and row.get('share_limit_action')!=action)):
        api('torrents/setShareLimits',{'hashes':row['hash'],'ratioLimit':-1,
            'seedingTimeLimit':-1,'inactiveSeedingTimeLimit':-1,
            'shareLimitAction':action or row.get('share_limit_action') or 'Stop'})


def initial_managed_ratio(hashes,target,ratio_only=False,adaptive=False,stop_on_complete=False):
    initial_ratio_limit(hashes,target,ratio_only=ratio_only,adaptive=adaptive,stop_on_complete=stop_on_complete)  # Persist before add.
    return -1


def seeding_completion(row,credit):
    active=row.get('state') in {'uploading','stalledUP','forcedUP'}
    ratio=real_ratio(credit) if 'ratio' in credit else real_ratio(row)
    seconds=credit.get('seeding_time',row.get('seeding_time'))
    unlimited=row.get('share_limit_action') != 'RemoveWithContent'
    reached=not unlimited and (ratio>=credit['ratio_limit'] or (not credit.get('ratio_only',False) and
        type(seconds) in (int,float) and math.isfinite(seconds) and seconds>=SEEDING_SECONDS+credit.get('extra_seed_hours',0)*3600))
    peers=row.get('num_leechs')
    speed=row.get('upspeed')
    known=(type(peers) is int and peers>=0 and type(speed) in (int,float)
           and math.isfinite(speed) and speed>=0)
    waiting=bool(active and reached and (not known or peers>0 or speed>0))
    extended=bool(active and reached and credit.get('adaptive_seeding') and credit.get('seeding_upload_potential'))
    return {'seeding_unlimited':unlimited,'seeding_goal_reached':bool(reached),'waiting_for_downloaders':waiting,
            'seeding_auto_extended':extended,
            'seeding_peer_status_known':known}


def finish_seeding(api,row,credit):
    from library_conversion import pending
    if pending(row['hash']):return
    from download_storage import read, CONFIG
    entries=read(CONFIG/'download-storage.json',{})
    record=next((entries.get(row.get(k)) for k in ('hash','infohash_v1','infohash_v2')
                 if entries.get(row.get(k))),None)
    if record and record.get('convert'):
        from conversion import finish
        return finish(api,row,credit,record)
    if credit.get('stop_on_complete'):
        # This explicit policy stops immediately, regardless of peers or ratio.
        # Keep the torrent, files and durable policy; never resume paused torrents.
        if (row.get('share_limit_action') == 'Stop'
                and row.get('state') in {'uploading','stalledUP','forcedUP','queuedUP'}
                and type(row.get('progress')) in (int,float) and row['progress'] >= 1):
            api('torrents/stop', {'hashes':row['hash']})
        return
    completion=seeding_completion(row,credit)
    if (row.get('state') not in {'uploading','stalledUP','forcedUP'}
            or not completion['seeding_goal_reached'] or completion['waiting_for_downloaders']
            or completion['seeding_auto_extended']):
        return
    action=row.get('share_limit_action')
    if action=='RemoveWithContent':
        from deletion_events import delete_completed
        return delete_completed(api, row, credit)


def extra_seed_hours(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0 <= value <= 8760:
        raise ValueError('Ekstra seedtid skal være mellem 0 og 8760 timer.')
    return float(value)


def share_policy(data):
    value = data.get('ratio_limit', -1)
    action = data.get('ratio_action', 'keep')
    if action == 'stop_keep':
        return {'ratio_limit':1.0, 'ratio_action':action}
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        raise ValueError('Vælg en gyldig stop-ratio.') from None
    if isinstance(value, bool) or not math.isfinite(ratio) or not (ratio == -1 or 0 <= ratio <= 10000):
        raise ValueError('Stop-ratio skal være mellem 0 og 10000.')
    if action not in ('keep', 'delete', 'delete_ratio', 'automatic') or (action != 'keep' and ratio < 0):
        raise ValueError('Vælg en stop-ratio og hvad der skal ske med filerne.')
    return {'ratio_limit':ratio, 'ratio_action':action}


def call(path, data=None, files=None):
    with requests.Session() as client:
        client.trust_env = False
        response = client.request('POST' if data is not None or files else 'GET', BASE + path,
            data=data, files=files, headers={'Referer':'http://127.0.0.1:8080/'}, timeout=5,
            allow_redirects=False)
        response.raise_for_status()
        return response


def execute(action, data):
    prefs = call('app/preferences').json()
    if prefs.get('current_network_interface') != 'tun0' or prefs.get('upnp') is not False:
        raise RuntimeError('Unsafe qBittorrent network settings')
    if action in ('rss_prepare','rss_resolve'):
        from rss_gate import gate_rpc
        from qbit_worker import ready
        ready()
        return gate_rpc(action,data,call)
    if action == 'rss_sync':
        from rss import sync_snapshot
        sync_snapshot()
        return {'ok':True}
    if action == 'traffic_history':
        # Once per ten minutes, independently of whether the browser is open.
        stats=call('sync/maindata?rid=0').json().get('server_state',{})
        return {key:stats.get(field) for key,field in (('real_uploaded','alltime_ul'),('real_downloaded','alltime_dl'))}
    if action == 'status':
        from download_storage import moving_progress, read as storage_read, CONFIG as storage_config
        storage_entries = storage_read(storage_config/'download-storage.json', {})
        fields = ('hash','name','size','progress','dlspeed','upspeed','state','ratio','num_seeds','num_leechs','num_complete','num_incomplete','eta',
                  'ratio_limit','share_limit_action','infohash_v1','infohash_v2','completed','tags',
                  'seeding_time','seeding_time_limit','uploaded','downloaded','added_on','priority')
        torrents=[]
        with CreditLedger().transaction() as ledger:
            rows = call('torrents/info').json()
            credits=[ledger.update(row) for row in rows]
            ledger.save()
            for row,credit in zip(rows,credits):
                apply_limits(call,row)
                if any(storage_entries.get(row.get(k),{}).get('convert') for k in ('hash','infohash_v1','infohash_v2')):
                    credit={**credit,'ratio_limit':1,'ratio_only':False,'adaptive_seeding':False,
                            'stop_on_complete':False,'extra_seed_hours':0}
                torrents.append({**{k:row.get(k) for k in fields},**credit,
                    'seeding_time_limit':SEEDING_MINUTES+credit.get('extra_seed_hours',0)*60 if row.get('share_limit_action')=='RemoveWithContent' and not credit.get('ratio_only',False) else -1,**stop_requirement({**row,**credit}),
                    **seeding_completion(row,credit), **moving_progress(row,storage_entries)})
        return {'torrents':torrents,
                'download_queue':download_queue_summary(rows),
                'transfer':call('transfer/info').json(), 'port':prefs['listen_port'],
                'interface':prefs['current_network_interface'], 'version':call('app/version').text}
    if action=='library-bitrates':
        from media_bitrates import listing
        return listing(data.get('files',[]))
    if action in ('library-shared-queue','library-shared-status','library-shared-complete','library-shared-cancel','library-shared-error'):
        import shared_library
        if action=='library-shared-queue':return shared_library.queue(call,data)
        if action=='library-shared-complete':return shared_library.complete(call,data.get('id'),data.get('device'))
        if action=='library-shared-cancel':return shared_library.cancel(call,data.get('id'),data.get('device'))
        if action=='library-shared-error':return shared_library.failed(data.get('id'),data.get('device'),data.get('detail'))
        return shared_library.status(call,data.get('id'),data.get('device'))
    if action in ('library-list','library-convert','library-retry','library-cancel'):
        from library_conversion import listing, queue, retry, cancel
        if action == 'library-list':return listing(call)
        if action == 'library-convert':return queue(call,data.get('id'),data.get('bitrate'))
        if action == 'library-cancel':cancel(data.get('id'));return {'ok':True}
        retry(data.get('id'));return {'ok':True}
    if action == 'conversion-retry':
        ident=data.get('hash','')
        if not re.fullmatch('[a-f0-9]{40}|[a-f0-9]{64}',ident):raise ValueError('Invalid hash')
        from conversion import retry
        retry(ident)
        return {'ok':True}
    if action == 'add':
        from conversion import choice
        convert=choice(data.get('convert',False))
        if convert:
            data={**data,'ratio_limit':1,'ratio_action':'delete'}
        policy = share_policy(data)
        from torrent_meta import magnet_meta, torrent_meta
        meta=magnet_meta(data['magnet']) if data.get('magnet') else torrent_meta(base64.b64decode(data['torrent'],validate=True))
        from download_storage import prepare
        options = {'savepath':prepare(meta['hashes'],name=meta.get('name',''),convert=convert), 'autoTMM':'false', 'stopped':'false', 'forceStart':'false',
                   'ratioLimit':initial_managed_ratio(meta['hashes'],seed_ratio(policy['ratio_limit']),ratio_only=policy['ratio_action']=='delete_ratio',adaptive=policy['ratio_action']=='automatic',stop_on_complete=policy['ratio_action']=='stop_keep'),
                   'seedingTimeLimit':-1, 'inactiveSeedingTimeLimit':-1,
                   'shareLimitAction':'RemoveWithContent' if policy['ratio_action'] not in ('keep','stop_keep') else 'Stop'}
        if data.get('magnet'):
            response = call('torrents/add', {**options, 'urls':data['magnet']})
        else:
            raw = base64.b64decode(data['torrent'], validate=True)
            response = call('torrents/add', options,
                            {'torrents':('upload.torrent', io.BytesIO(raw), 'application/x-bittorrent')})
        if response.text.strip() != 'Ok.':
            result = response.json()
            if (result.get('failure_count', 0) or
                    result.get('success_count', 0) + result.get('pending_count', 0) < 1):
                raise ValueError('qBittorrent rejected torrent')
    elif action == 'ratio':
        ident=data.get('hash','')
        if not re.fullmatch(r'[a-fA-F0-9]{40}|[a-fA-F0-9]{64}',ident):
            raise ValueError('Invalid hash')
        from download_storage import read,CONFIG
        if read(CONFIG/'download-storage.json',{}).get(ident.lower(),{}).get('convert'):
            raise ValueError('Konverterede downloads bruger ratio 1:1 eller 49 timers seeding.')
        policy=share_policy(data)
        ratio=policy['ratio_limit']
        extra=extra_seed_hours(data['extra_seed_hours']) if 'extra_seed_hours' in data else None
        if ratio<1:
            raise ValueError('Stop-ratio skal være mindst 1.')
        with CreditLedger().transaction() as ledger:
            rows=call('torrents/info?hashes='+ident).json()
            if len(rows)!=1 or rows[0].get('hash','').lower()!=ident.lower():
                raise ValueError('Torrent not found')
            ledger.update(rows[0],target=ratio)
            if 'ratio_action' in data:
                ledger.entries[ident.lower()]['ratio_only']=policy['ratio_action']=='delete_ratio'
                ledger.entries[ident.lower()]['adaptive_seeding']=policy['ratio_action']=='automatic'
                ledger.entries[ident.lower()]['stop_on_complete']=policy['ratio_action']=='stop_keep'
                if policy['ratio_action']!='automatic':
                    ledger.entries[ident.lower()].pop('upload_potential',None)
            if extra is not None:
                ledger.entries[ident.lower()]['extra_seed_hours']=extra
            ledger.save()
            selected=('RemoveWithContent' if policy['ratio_action'] not in ('keep','stop_keep') else 'Stop') if 'ratio_action' in data else None
            apply_limits(call,rows[0],action=selected)
    elif action in ('start','stop','delete','delete-files'):
        if not re.fullmatch(r'[a-fA-F0-9]{40}|[a-fA-F0-9]{64}', data.get('hash','')):
            raise ValueError('Invalid hash')
        payload = {'hashes':data['hash']}
        if action=='delete' and type(data.get('delete_files',False)) is not bool:
            raise ValueError('Invalid file deletion choice')
        if action in ('stop','delete','delete-files'):
            with CreditLedger().transaction() as ledger:
                rows=call('torrents/info?hashes='+data['hash']).json()
                if len(rows)!=1 or rows[0].get('hash','').lower()!=data['hash'].lower():
                    raise ValueError('Torrent not found')
                credit=ledger.update(rows[0])
            requirement=stop_requirement({**rows[0],**credit})
            if not requirement['seeding_requirement_met'] and data.get('confirm_early_stop') is not True:
                raise SeedingRequirementError(requirement['stop_reason'])
        if action=='delete-files':
            from download_storage import delete_torrent_files
            # The background publisher/auto-remover uses the same ledger lock.
            with CreditLedger().transaction():
                return delete_torrent_files(call,rows[0],prefs)
        if action == 'delete':
            payload['deleteFiles'] = 'true' if data.get('delete_files',False) else 'false'
        if action=='start':
            from download_storage import files_deleted,prepare_file_restart
            if files_deleted(data['hash'].lower()):
                prepare_file_restart(data['hash'].lower())
                call('torrents/recheck',payload)
        call('torrents/' + action, payload)
        if action=='start':
            from download_storage import set_files_deleted
            set_files_deleted([data['hash'].lower()],False)
        if action=='delete':
            from download_storage import forget
            forget([data['hash'].lower()])
            with CreditLedger().transaction() as ledger:
                ledger.entries.pop(data['hash'].lower(),None)
    else:
        raise ValueError('Unsupported operation')
    return {'ok':True}


if __name__ == '__main__':
    job={}
    try:
        ident = sys.argv[1]
        if not re.fullmatch('[a-f0-9]{32}', ident):
            raise ValueError()
        job = json.loads((Path('/rpc') / (ident + '.json')).read_text())
        print(json.dumps(execute(job['action'], job.get('data', {}))))
    except SeedingRequirementError as exc:
        print(json.dumps({'error':str(exc),'code':'seeding_requirement'}))
        sys.exit(1)
    except ValueError as exc:
        message=str(exc) if job.get('action','').startswith('library-') else 'qBittorrent kunne ikke udføre handlingen. Kontrollér VPN-status og torrentfilen.'
        print(json.dumps({'error':message}))
        sys.exit(1)
    except Exception:
        print(json.dumps({'error':'qBittorrent kunne ikke udføre handlingen. Kontrollér VPN-status og torrentfilen.'}))
        sys.exit(1)
