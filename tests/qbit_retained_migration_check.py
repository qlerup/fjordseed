"""Run in a disposable network-disabled container with empty download mounts."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import time

import download_storage as storage
from qbit_rpc import call
from qbit_worker import configure,stop_process


def encode(value):
    if isinstance(value,dict):return b'd'+b''.join(encode(k)+encode(v) for k,v in sorted(value.items()))+b'e'
    if isinstance(value,int):return b'i'+str(value).encode()+b'e'
    if isinstance(value,str):value=value.encode()
    return str(len(value)).encode()+b':'+value


def wait_for(predicate):
    for _ in range(120):
        rows=call('torrents/info').json()
        if predicate(rows):return rows
        time.sleep(.1)
    raise AssertionError([(r['name'],r['state'],r['save_path']) for r in rows])


configure(45001)
process=subprocess.Popen(['qbittorrent-nox','--profile=/config','--webui-port=8080','--confirm-legal-notice'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:call('app/preferences');break
        except Exception:time.sleep(.1)
    call('app/setPreferences',{'json':json.dumps({'current_network_interface':'lo','dht':False,'pex':False,'lsd':False})})
    source=Path('/downloads/Old');source.mkdir()
    (source/'unrelated.txt').write_text('Keep unrelated files')
    library=Path('/download-locations')/('a'*32);library.mkdir()
    existing=library/'legacy.bin';existing.mkdir();(existing/'keep.txt').write_text('Never overwrite')
    records={}
    for kind in ('legacy','managed','temporary','incomplete'):
        name=kind+'.bin';payload=('Synthetic '+kind).encode()
        info={'name':name,'length':len(payload),'piece length':16384,'pieces':hashlib.sha1(payload).digest()}
        ident=hashlib.sha1(encode(info)).hexdigest()
        if kind!='incomplete':(source/name).write_bytes(payload)
        records[kind]=(ident,name,payload)
        call('torrents/add',{'savepath':str(source),'autoTMM':'false','stopped':'false','ratioLimit':-1,
            'shareLimitAction':'RemoveWithContent' if kind=='temporary' else 'Stop'},
            {'torrents':(name+'.torrent',io.BytesIO(encode({'info':info})),'application/x-bittorrent')})
    rows=wait_for(lambda rows:len(rows)==4 and all(r['state']=='stalledUP' for r in rows if r['name']!='incomplete.bin'))
    with storage.transaction() as entries:
        entries[records['managed'][0]]={'stage':'/downloads/old-buffer','target':str(source),'published':True}
    storage.SETTINGS.write_text(json.dumps({'path':str(library),'streaming_enabled':True,'retained_library_path':str(library)}))
    for _ in range(150):
        rows=call('torrents/info').json()
        assert storage.publish_complete(call,rows)==[]
        saved=storage.read(storage.CONFIG/'download-storage.json',{})
        if all(saved.get(records[k][0],{}).get('migration') and saved[records[k][0]].get('published')
               for k in ('legacy','managed')):break
        time.sleep(.1)
    else:raise AssertionError('Migration did not finish')
    rows=wait_for(lambda rows:all(r['state']=='stalledUP' for r in rows if r['name'] in ('legacy.bin','managed.bin'))
                  and all(not (source/records[k][1]).exists() for k in ('legacy','managed')))
    for kind in ('legacy','managed'):
        ident,name,payload=records[kind]
        row=next(r for r in rows if r['hash']==ident)
        target=Path(saved[ident]['target'])
        assert row['save_path'].rstrip('/')==str(target)
        assert (target/name).read_bytes()==payload
        assert not (source/name).exists()
        assert not (target/storage.PUBLISHING_MARKER).exists()
        assert row['progress']==1 and row['state']=='stalledUP'
    for kind in ('temporary','incomplete'):
        row=next(r for r in rows if r['hash']==records[kind][0])
        assert row['save_path'].rstrip('/')==str(source)
    assert (source/'unrelated.txt').read_text()=='Keep unrelated files'
    assert (existing/'keep.txt').read_text()=='Never overwrite'
    print('PASS real qBittorrent: legacy and retained torrents moved, identical payloads, seeding resumed, unrelated/colliding files preserved; temporary/incomplete torrents stayed put')
finally:stop_process(process)
