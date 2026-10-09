"""Run only in a disposable container with --network none and empty volumes."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,'/checks')
sys.path.insert(1,'/app')
from qbit_worker import configure, stop_process
from qbit_rpc import call, DOWNLOAD_QUEUE_PREFERENCES, sync_download_queue


def encode(value):
    if isinstance(value,dict):
        return b'd'+b''.join(encode(k)+encode(v) for k,v in sorted(value.items()))+b'e'
    if isinstance(value,int):
        return b'i'+str(value).encode()+b'e'
    if isinstance(value,str):value=value.encode()
    return str(len(value)).encode()+b':'+value


def wait_for(check,description):
    until=time.monotonic()+65
    while time.monotonic()<until:
        rows=call('torrents/info').json()
        if check(rows):return rows
        time.sleep(.5)
    raise AssertionError((description,[(r['name'],r['state'],r['progress']) for r in rows]))


configure(45001)
process=subprocess.Popen(['qbittorrent-nox','--profile=/config','--webui-port=8080','--confirm-legal-notice'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:prefs=call('app/preferences').json();break
        except Exception:time.sleep(.2)
    assert all(prefs.get(k)==v for k,v in DOWNLOAD_QUEUE_PREFERENCES.items()),prefs
    # Loopback-only test: there is no external network or real torrent data.
    call('app/setPreferences',{'json':json.dumps({'current_network_interface':'lo','dht':False,'pex':False,'lsd':False})})
    call('app/setPreferences',{'json':json.dumps({'max_active_downloads':3,'max_active_uploads':3,'max_active_torrents':5,'dont_count_slow_torrents':True})})
    sync_download_queue()
    pending={}
    for i in range(12):
        name=f'queue-fixture-{i}.bin';data=f'Local queue test file {i}'.encode()
        info={'name':name,'length':len(data),'piece length':16384,'pieces':hashlib.sha1(data).digest()}
        ident=hashlib.sha1(encode(info)).hexdigest()
        if i>=10:(Path('/downloads')/name).write_bytes(data)
        else:pending[ident]=(name,data)
        tag='FjordSeed-RSS-test' if i%2 else 'manual'
        response=call('torrents/add',{'savepath':'/downloads','stopped':'false','forceStart':'false','tags':tag},
                      {'torrents':(name+'.torrent',io.BytesIO(encode({'info':info})),'application/x-bittorrent')})
        assert response.status_code==200
    def queued(rows):
        incomplete=[r for r in rows if r['hash'] in pending]
        return (len(rows)==12 and len([r for r in incomplete if r['state']=='queuedDL'])==2
            and all(r['progress']==1 and r['state']=='stalledUP' for r in rows if r['hash'] not in pending))
    rows=wait_for(queued,'8 active mixed manual/RSS downloads and 2 queued; 2 seeders stay active')
    active=[r for r in rows if r['hash'] in pending and r['state']=='stalledDL']
    assert len(active)==8
    previous_queue={r['hash'] for r in rows if r['state']=='queuedDL'}
    completed=active[0]['hash'];name,data=pending[completed]
    (Path('/downloads')/name).write_bytes(data)
    call('torrents/recheck',{'hashes':completed})
    def promoted(rows):
        return (next(r for r in rows if r['hash']==completed)['state']=='stalledUP'
            and len([r for r in rows if r['state']=='queuedDL'])==1
            and any(r['hash'] in previous_queue and r['state']=='stalledDL' for r in rows)
            and len([r for r in rows if r['state']=='stalledDL'])==8)
    wait_for(promoted,'completion releases slot and promotes next queued download without stopping seeders')
    print('PASS real qBittorrent: persisted/migrated queue preferences, 8 mixed manual/RSS downloads, 2 queued, seeders unlimited, completion promotes next',flush=True)
finally:
    stop_process(process)
