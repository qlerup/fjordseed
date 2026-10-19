"""Disposable image only: --network none, empty writable /config and /downloads."""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import time

import download_storage as storage
from qbit_worker import configure,stop_process
from qbit_rpc import call


def bencode(value):
    if isinstance(value,dict):return b'd'+b''.join(bencode(k)+bencode(v) for k,v in sorted(value.items()))+b'e'
    if isinstance(value,int):return b'i'+str(value).encode()+b'e'
    if isinstance(value,str):value=value.encode()
    return str(len(value)).encode()+b':'+value


payload=b'fixture-bytes'*4096
info={'name':'Fixture.bin','length':len(payload),'piece length':16384,
      'pieces':b''.join(hashlib.sha1(payload[i:i+16384]).digest() for i in range(0,len(payload),16384))}
ident=hashlib.sha1(bencode(info)).hexdigest()
stage=Path(storage.prepare([ident]));(stage/'Fixture.bin').write_bytes(payload)
unrelated=stage/'Unrelated.txt';unrelated.write_text('Keep this file')
configure(45001)
process=subprocess.Popen(['qbittorrent-nox','--profile=/config','--webui-port=8080','--confirm-legal-notice'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:call('app/version');break
        except Exception:time.sleep(.1)
    call('app/setPreferences',{'json':'{"current_network_interface":"lo","dht":false,"pex":false,"lsd":false}'})
    call('torrents/add',{'savepath':str(stage),'autoTMM':'false','stopped':'false'},
         {'torrents':('fixture.torrent',io.BytesIO(bencode({'info':info})),'application/x-bittorrent')})
    for _ in range(100):
        rows=call('torrents/info?hashes='+ident).json()
        if rows and rows[0]['progress']==1:break
        time.sleep(.1)
    assert rows and rows[0]['progress']==1,rows
    result=storage.delete_torrent_files(call,rows[0],{})
    assert result['torrent_retained'] and result['deleted_files']==1
    assert not (stage/'Fixture.bin').exists() and unrelated.read_text()=='Keep this file'
    rows=call('torrents/info?hashes='+ident).json()
    assert len(rows)==1 and rows[0]['state'] in ('stoppedUP','stoppedDL')
    assert storage.files_deleted(ident)
    assert storage.publish_complete(call,rows)==[]
    assert storage.moving_progress(rows[0],storage.read(storage.CONFIG/'download-storage.json',{}))['progress']==0
    # Explicitly restarting can recheck the removed files; no automatic restart.
    storage.prepare_file_restart(ident)
    assert (stage/storage.PUBLISHING_MARKER).exists()
    call('torrents/recheck',{'hashes':ident});call('torrents/start',{'hashes':ident})
    for _ in range(100):
        row=call('torrents/info?hashes='+ident).json()[0]
        if row['progress']==0 and row['state'] in ('stalledDL','downloading','queuedDL'):break
        time.sleep(.1)
    assert row['progress']==0 and row['state'] in ('stalledDL','downloading','queuedDL'),row['state']
    # Traversing a symlink must not touch its external target.
    external=Path('/config/never-delete.txt');external.write_text('protected')
    link=stage/'link';link.symlink_to(external)
    try:storage.check_file_plan([('/downloads',str(link.relative_to('/downloads')))],remove=True)
    except ValueError:pass
    else:raise AssertionError('Symlink deletion was not refused')
    assert external.read_text()=='protected'
    print('PASS actual qBittorrent: files removed, torrent retained/stopped, unrelated files retained, explicit restart rechecks, symlinks refused')
finally:stop_process(process)
