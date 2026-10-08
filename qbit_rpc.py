"""Allowlisted qBittorrent RPC executed inside the VPN network namespace."""
import base64
import io
import json
from pathlib import Path
import re
import sys

import requests

BASE = 'http://127.0.0.1:8080/api/v2/'


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
    if action == 'status':
        rows = call('torrents/info?limit=500').json()
        fields = ('hash','name','size','progress','dlspeed','upspeed','state','ratio','num_seeds','num_leechs','eta')
        return {'torrents':[{k:r.get(k) for k in fields} for r in rows],
                'transfer':call('transfer/info').json(), 'port':prefs['listen_port'],
                'interface':prefs['current_network_interface'], 'version':call('app/version').text}
    if action == 'add':
        if data.get('magnet'):
            response = call('torrents/add', {'urls':data['magnet'], 'savepath':'/downloads', 'stopped':'false'})
        else:
            raw = base64.b64decode(data['torrent'], validate=True)
            response = call('torrents/add', {'savepath':'/downloads', 'stopped':'false'},
                            {'torrents':('upload.torrent', io.BytesIO(raw), 'application/x-bittorrent')})
        if response.text.strip() != 'Ok.':
            raise ValueError('qBittorrent rejected torrent')
    elif action in ('start','stop','delete'):
        if not re.fullmatch(r'[a-fA-F0-9]{40}|[a-fA-F0-9]{64}', data.get('hash','')):
            raise ValueError('Invalid hash')
        payload = {'hashes':data['hash']}
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
    except Exception:
        print(json.dumps({'error':'qBittorrent kunne ikke udføre handlingen. Kontrollér VPN-status og torrentfilen.'}))
        sys.exit(1)
