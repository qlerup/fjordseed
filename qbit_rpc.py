"""Allowlisted qBittorrent RPC executed inside the VPN network namespace."""
import base64
import io
import json
import math
from pathlib import Path
import re
import sys

import requests
from green_credit import CreditLedger

BASE = 'http://127.0.0.1:8080/api/v2/'
SEEDING_BASE_HOURS = 48
SEEDING_BUFFER_HOURS = 1
SEEDING_MINUTES = (SEEDING_BASE_HOURS + SEEDING_BUFFER_HOURS) * 60
SEEDING_SECONDS = SEEDING_MINUTES * 60


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
    ratio=row.get('credited_ratio',row.get('ratio'))
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
        for row in rows:
            credit=ledger.update(row)
            apply_limits(api,row,credit['native_ratio_limit'])


def apply_limits(api,row,target,action=None):
    if (row.get('ratio_limit')!=target or row.get('seeding_time_limit')!=SEEDING_MINUTES
            or row.get('inactive_seeding_time_limit')!=-1
            or (action is not None and row.get('share_limit_action')!=action)):
        api('torrents/setShareLimits',{'hashes':row['hash'],'ratioLimit':target,
            'seedingTimeLimit':SEEDING_MINUTES,'inactiveSeedingTimeLimit':-1,
            'shareLimitAction':action or row.get('share_limit_action') or 'Stop'})


def share_policy(data):
    value = data.get('ratio_limit', -1)
    action = data.get('ratio_action', 'keep')
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        raise ValueError('Vælg en gyldig stop-ratio.') from None
    if isinstance(value, bool) or not math.isfinite(ratio) or not (ratio == -1 or 0 <= ratio <= 10000):
        raise ValueError('Stop-ratio skal være mellem 0 og 10000.')
    if action not in ('keep', 'delete') or (action == 'delete' and ratio < 0):
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
    if action == 'status':
        fields = ('hash','name','size','progress','dlspeed','upspeed','state','ratio','num_seeds','num_leechs','eta',
                  'ratio_limit','share_limit_action','infohash_v1','infohash_v2','completed','tags',
                  'seeding_time','seeding_time_limit','uploaded','downloaded','added_on')
        torrents=[]
        with CreditLedger().transaction() as ledger:
            rows = call('torrents/info?limit=500').json()
            for row in rows:
                credit=ledger.update(row)
                apply_limits(call,row,credit['native_ratio_limit'])
                torrents.append({**{k:row.get(k) for k in fields},**credit,
                    'seeding_time_limit':SEEDING_MINUTES,**stop_requirement({**row,**credit})})
        return {'torrents':torrents,
                'transfer':call('transfer/info').json(), 'port':prefs['listen_port'],
                'interface':prefs['current_network_interface'], 'version':call('app/version').text}
    if action == 'add':
        policy = share_policy(data)
        from torrent_meta import magnet_meta, torrent_meta
        try:
            meta=magnet_meta(data['magnet']) if data.get('magnet') else torrent_meta(base64.b64decode(data['torrent'],validate=True))
        except ValueError:
            meta={'hashes':[]}
        with CreditLedger().transaction() as ledger:
            ledger.register(meta['hashes'],seed_ratio(policy['ratio_limit']))
            pending=ledger.policies.get('_enabled',False)
        options = {'savepath':'/downloads', 'stopped':'false', 'ratioLimit':seed_ratio(policy['ratio_limit']),
                   'seedingTimeLimit':SEEDING_MINUTES, 'inactiveSeedingTimeLimit':-1,
                   'shareLimitAction':'RemoveWithContent' if policy['ratio_action'] == 'delete' else 'Stop'}
        if pending:
            options['ratioLimit']*=2
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
        policy=share_policy(data)
        ratio=policy['ratio_limit']
        if ratio<1:
            raise ValueError('Stop-ratio skal være mindst 1.')
        with CreditLedger().transaction() as ledger:
            rows=call('torrents/info?hashes='+ident).json()
            if len(rows)!=1 or rows[0].get('hash','').lower()!=ident.lower():
                raise ValueError('Torrent not found')
            credit=ledger.update(rows[0],target=ratio)
            selected=('RemoveWithContent' if policy['ratio_action']=='delete' else 'Stop') if 'ratio_action' in data else None
            apply_limits(call,rows[0],credit['native_ratio_limit'],action=selected)
    elif action in ('start','stop','delete'):
        if not re.fullmatch(r'[a-fA-F0-9]{40}|[a-fA-F0-9]{64}', data.get('hash','')):
            raise ValueError('Invalid hash')
        payload = {'hashes':data['hash']}
        if action in ('stop','delete'):
            with CreditLedger().transaction() as ledger:
                rows=call('torrents/info?hashes='+data['hash']).json()
                if len(rows)!=1 or rows[0].get('hash','').lower()!=data['hash'].lower():
                    raise ValueError('Torrent not found')
                credit=ledger.update(rows[0])
            requirement=stop_requirement({**rows[0],**credit})
            if not requirement['seeding_requirement_met'] and data.get('confirm_early_stop') is not True:
                raise SeedingRequirementError(requirement['stop_reason'])
        if action == 'delete':
            payload['deleteFiles'] = 'false'
        call('torrents/' + action, payload)
        if action=='delete':
            with CreditLedger().transaction() as ledger:
                ledger.entries.pop(data['hash'].lower(),None)
    else:
        raise ValueError('Unsupported operation')
    return {'ok':True}


if __name__ == '__main__':
    try:
        ident = sys.argv[1]
        if not re.fullmatch('[a-f0-9]{32}', ident):
            raise ValueError()
        job = json.loads((Path('/rpc') / (ident + '.json')).read_text())
        print(json.dumps(execute(job['action'], job.get('data', {}))))
    except SeedingRequirementError as exc:
        print(json.dumps({'error':str(exc),'code':'seeding_requirement'}))
        sys.exit(1)
    except Exception:
        print(json.dumps({'error':'qBittorrent kunne ikke udføre handlingen. Kontrollér VPN-status og torrentfilen.'}))
        sys.exit(1)
