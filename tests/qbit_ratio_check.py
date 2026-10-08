"""Run in a disposable, network=none container with ephemeral /downloads.

Never run against a production qBittorrent profile or download directory.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import time

import requests
from rss import sync_rss


def bencode(value):
    if isinstance(value,int):
        return b'i'+str(value).encode()+b'e'
    if isinstance(value,bytes):
        return str(len(value)).encode()+b':'+value
    if isinstance(value,dict):
        return b'd'+b''.join(bencode(k)+bencode(value[k]) for k in sorted(value))+b'e'
    raise TypeError(value)


root=Path('/tmp/ratio-check')
config=root/'qBittorrent/config'
config.mkdir(parents=True)
(config/'qBittorrent.conf').write_text('[LegalNotice]\nAccepted=true\n[Preferences]\nWebUI\\Address=127.0.0.1\nWebUI\\Port=8080\nWebUI\\LocalHostAuth=false\n[BitTorrent]\nSession\\DHTEnabled=false\nSession\\PeXEnabled=false\nSession\\LSDEnabled=false\n')
process=subprocess.Popen(['qbittorrent-nox','--profile='+str(root),'--webui-port=8080','--confirm-legal-notice'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
client=requests.Session()
client.trust_env=False
client.headers['Referer']='http://127.0.0.1:8080/'


def api(path,data=None,files=None):
    response=client.request('POST' if data is not None else 'GET','http://127.0.0.1:8080/api/v2/'+path,
        data=data,files=files,timeout=2)
    response.raise_for_status()
    return response


def wait_for(check):
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        try:
            if check():
                return
        except requests.RequestException:
            pass
        time.sleep(.25)
    raise AssertionError('Timed out waiting for qBittorrent')


try:
    wait_for(lambda:api('app/version').ok)
    ident='a'*32
    sync_rss([{'id':ident,'name':'Offline RSS rule','url':'https://fixture.example/rss',
        'folder':'rss-fixture','enabled':False,'include':'Linux','ratio_limit':2.5,'ratio_action':'delete'}],api)
    rule=api('rss/rules').json()['FjordSeed-'+ident]
    params=rule['torrentParams']
    assert params['save_path']=='/downloads/rss-fixture' and params['ratio_limit']==2.5, params
    assert params['share_limit_action']=='RemoveWithContent', params
    assert params['tags']==['FjordSeed-RSS-'+ident], params
    assert rule['enabled'] is False and api('app/preferences').json()['rss_auto_downloading_enabled'] is False
    print('PASS: native RSS rule retains folder, tag, ratio and automatic file action')
    sync_rss([],api)
    assert 'FjordSeed-'+ident not in api('rss/rules').json()
    for action in ('Stop','RemoveWithContent'):
        name=action.encode()+b'.bin'
        content=b'offline-ratio-fixture-'+name
        path=Path('/downloads')/name.decode()
        path.write_bytes(content)
        info={b'length':len(content),b'name':name,b'piece length':16384,b'pieces':hashlib.sha1(content).digest()}
        torrent=bencode({b'info':info})
        ident=hashlib.sha1(bencode(info)).hexdigest()
        response=api('torrents/add',{'savepath':'/downloads','stopped':'false','ratioLimit':0,
            'seedingTimeLimit':-1,'inactiveSeedingTimeLimit':-1,'shareLimitAction':action},
            {'torrents':('fixture.torrent',torrent,'application/x-bittorrent')})
        result=response.json()
        assert result['success_count']==1 and result['failure_count']==0, result
        if action=='Stop':
            wait_for(lambda:any(t['hash']==ident and t['state']=='stoppedUP' for t in api('torrents/info').json()))
            assert path.read_bytes()==content
            row=next(t for t in api('torrents/info').json() if t['hash']==ident)
            print('Stop reached; file preserved; policy fields:',{k:v for k,v in row.items() if 'ratio' in k or 'limit_action' in k})
        else:
            wait_for(lambda:not path.exists() and not any(t['hash']==ident for t in api('torrents/info').json()))
            print('RemoveWithContent reached; fixture torrent and file deleted')
    print('PASS: native ratio stop and automatic deletion in offline disposable container')
finally:
    process.terminate()
    process.wait(timeout=10)
