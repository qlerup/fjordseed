"""Disposable, network-disabled qBittorrent container; synthetic files only."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0, '/checks')
from qbit_worker import configure, stop_process
from qbit_rpc import call
from download_storage import prepare, publish_complete, CONFIG, read


def encode(value):
    if isinstance(value,dict):
        return b'd'+b''.join(encode(k)+encode(v) for k,v in sorted(value.items()))+b'e'
    if isinstance(value,int):return b'i'+str(value).encode()+b'e'
    if isinstance(value,str):value=value.encode()
    return str(len(value)).encode()+b':'+value


def wait_for(check):
    until=time.monotonic()+30
    while time.monotonic()<until:
        rows=call('torrents/info').json()
        if check(rows):return rows
        time.sleep(.25)
    raise AssertionError([(r['name'],r['state'],r['save_path']) for r in rows])


configure(45001)
process=subprocess.Popen(['qbittorrent-nox','--profile=/config','--webui-port=8080','--confirm-legal-notice'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:call('app/preferences');break
        except Exception:time.sleep(.2)
    call('app/setPreferences',{'json':json.dumps({'current_network_interface':'lo','dht':False,'pex':False,'lsd':False})})
    records={}
    for kind in ('keep','delete','incomplete','legacy'):
        name=kind+'.mp4';content=('synthetic '+kind).encode()
        info={'name':name,'length':len(content),'piece length':16384,'pieces':hashlib.sha1(content).digest()}
        ident=hashlib.sha1(encode(info)).hexdigest()
        stage=Path('/downloads') if kind=='legacy' else Path(prepare([ident],'film'))
        if kind!='incomplete':(stage/name).write_bytes(content)
        records[kind]=(ident,stage,name,content)
        call('torrents/add',{'savepath':str(stage),'autoTMM':'false','stopped':'false','ratioLimit':-1,
             'shareLimitAction':'RemoveWithContent' if kind=='delete' else 'Stop'},
             {'torrents':(name+'.torrent',io.BytesIO(encode({'info':info})),'application/x-bittorrent')})
    rows=wait_for(lambda rows:len(rows)==4 and all(r['progress']==1 for r in rows if r['name']!='incomplete.mp4'))
    assert publish_complete(call,rows)==[]
    ident,stage,name,content=records['keep']
    target=Path(read(CONFIG/'download-storage.json',{})[ident]['target'])
    rows=wait_for(lambda rows:any(r['hash']==ident and r['save_path'].rstrip('/')==str(target) and r['state']=='stalledUP' for r in rows))
    assert (target/name).read_bytes()==content and not (stage/name).exists()
    assert publish_complete(call,rows)==[]
    for kind in ('delete','incomplete','legacy'):
        ident,stage,name,content=records[kind]
        assert next(r for r in rows if r['hash']==ident)['save_path'].rstrip('/')==str(stage)
    # Metadata and save path survive a normal client restart.
    stop_process(process)
    process=subprocess.Popen(['qbittorrent-nox','--profile=/config','--webui-port=8080','--confirm-legal-notice'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:rows=call('torrents/info').json();break
        except Exception:time.sleep(.2)
    rows=wait_for(lambda rows:len(rows)==4)
    ident=records['keep'][0]
    assert next(r for r in rows if r['hash']==ident)['save_path'].rstrip('/')==str(target)
    print('PASS real qBittorrent: completed keep moved and still seeding; delete/incomplete/legacy stay put; restart persists location')
finally:
    stop_process(process)
