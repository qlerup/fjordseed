"""Allowlisted qBittorrent RPC executed inside the VPN network namespace."""
import base64
import io
import json
import math
from pathlib import Path
import re
import sys

import requests

BASE = 'http://127.0.0.1:8080/api/v2/'
SEEDING_MINUTES = 48 * 60
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
    ratio=row.get('ratio')
    seconds=row.get('seeding_time')
    ratio_done=type(ratio) in (int,float) and math.isfinite(ratio) and ratio>=target
    time_done=type(seconds) in (int,float) and math.isfinite(seconds) and seconds>=SEEDING_SECONDS
    allowed=bool(ratio_done or time_done)
    return {'seeding_requirement_met':allowed,'required_seeding_seconds':SEEDING_SECONDS,
            'stop_reason':'' if allowed else 'Torrenten har endnu ikke opfyldt kravet om ratio 1:1 eller 48 timers seeding. Hvis du stopper eller fjerner den nu, kan trackeren registrere det som hit-and-run.'}


def sync_share_limits(api=None):
    api=api or call
    rows=api('torrents/info').json()
    for row in rows:
        target=seed_ratio(row.get('ratio_limit'))
        if (row.get('ratio_limit')!=target or row.get('seeding_time_limit')!=SEEDING_MINUTES
                or row.get('inactive_seeding_time_limit')!=-1):
            api('torrents/setShareLimits',{'hashes':row['hash'],'ratioLimit':target,
                'seedingTimeLimit':SEEDING_MINUTES,'inactiveSeedingTimeLimit':-1,
                'shareLimitAction':row.get('share_limit_action','Stop')})


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
        rows = call('torrents/info?limit=500').json()
        fields = ('hash','name','size','progress','dlspeed','upspeed','state','ratio','num_seeds','num_leechs','eta',
                  'ratio_limit','share_limit_action','infohash_v1','infohash_v2','completed','tags',
                  'seeding_time','seeding_time_limit')
        return {'torrents':[{**{k:r.get(k) for k in fields},**stop_requirement(r)} for r in rows],
                'transfer':call('transfer/info').json(), 'port':prefs['listen_port'],
                'interface':prefs['current_network_interface'], 'version':call('app/version').text}
    if action == 'add':
        policy = share_policy(data)
        options = {'savepath':'/downloads', 'stopped':'false', 'ratioLimit':seed_ratio(policy['ratio_limit']),
                   'seedingTimeLimit':SEEDING_MINUTES, 'inactiveSeedingTimeLimit':-1,
                   'shareLimitAction':'RemoveWithContent' if policy['ratio_action'] == 'delete' else 'Stop'}
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
    elif action in ('start','stop','delete'):
        if not re.fullmatch(r'[a-fA-F0-9]{40}|[a-fA-F0-9]{64}', data.get('hash','')):
            raise ValueError('Invalid hash')
        payload = {'hashes':data['hash']}
        if action in ('stop','delete'):
            rows=call('torrents/info?hashes='+data['hash']).json()
            if len(rows)!=1 or rows[0].get('hash','').lower()!=data['hash'].lower():
                raise ValueError('Torrent not found')
            requirement=stop_requirement(rows[0])
            if not requirement['seeding_requirement_met'] and data.get('confirm_early_stop') is not True:
                raise SeedingRequirementError(requirement['stop_reason'])
        if action == 'delete':
            payload['deleteFiles'] = 'false'
        call('torrents/' + action, payload)
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
