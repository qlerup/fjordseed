"""Bounded, cached header probes for the PC workspace's video files."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time

import download_storage as storage
from conversion import checked
from library_conversion import VIDEO,key,fingerprint
from state import atomic

_lock=threading.Lock()


def number(value):
    try:
        result=float(value)
        return result if math.isfinite(result) and 0<result<10**12 else None
    except (ValueError,TypeError):return None


def probe(path):
    result=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
        'stream=bit_rate:stream_tags=BPS,BPS-eng,NUMBER_OF_BYTES,NUMBER_OF_BYTES-eng,DURATION,DURATION-eng:format=bit_rate,duration',
        '-of','json',str(path)],capture_output=True,text=True,check=True,timeout=2)
    data=json.loads(result.stdout);stream=(data.get('streams') or [{}])[0]
    tags=stream.get('tags',{});fmt=data.get('format',{})
    video=number(stream.get('bit_rate')) or number(tags.get('BPS')) or number(tags.get('BPS-eng'))
    if not video:
        duration=tags.get('DURATION',tags.get('DURATION-eng',''))
        try:
            hours,minutes,seconds=duration.split(':');seconds=float(hours)*3600+float(minutes)*60+float(seconds)
            size=number(tags.get('NUMBER_OF_BYTES',tags.get('NUMBER_OF_BYTES-eng')))
            video=size*8/seconds if size and seconds>0 else None
        except (ValueError,TypeError,AttributeError):pass
    total=number(fmt.get('bit_rate'))
    duration=number(fmt.get('duration'))
    if not total and duration:total=path.stat().st_size*8/duration
    return {'video_bps':video,'total_bps':total,'state':'ready' if video or total else 'unavailable'}


@contextmanager
def probe_slot():
    if not _lock.acquire(blocking=False):yield False;return
    handle=None;fcntl=None;locked=False
    try:
        storage.CONFIG.mkdir(parents=True,exist_ok=True)
        handle=(storage.CONFIG/'media-bitrates.lock').open('a')
        try:import fcntl
        except ImportError:pass
        if fcntl:
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:yield False;return
        locked=True;yield True
    finally:
        if handle:
            if fcntl and locked:fcntl.flock(handle,fcntl.LOCK_UN)
            handle.close()
        _lock.release()


def listing(files):
    root=checked(storage.download_root());paths=[]
    for folder,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=[d for d in dirs if not d.startswith('.') and d!='Seeder' and not (Path(folder)/d).is_symlink()]
        for name in names:
            path=Path(folder)/name
            if path.suffix.lower() not in VIDEO or path.is_symlink() or not path.is_file():continue
            paths.append((checked(path),path.relative_to(root).as_posix(),path.stat().st_size))
    cache_path=storage.CONFIG/'media-bitrates.json'
    cache=storage.read(cache_path,{})
    results=[];pending=False;probed=0
    with probe_slot() as available:
        if available:cache=storage.read(cache_path,{})
        for item in files:
            if item.get('converted'):continue
            name=item['name'];size=item['size']
            matches=[p for p,relative,length in paths if length==size and (relative==name or relative.endswith('/'+name))]
            entry={'state':'unavailable','video_bps':None,'total_bps':None}
            if len(matches)==1:
                path=matches[0];ident=key(path);signature=fingerprint(path)
                saved=cache.get(ident,{})
                valid=saved.get('fingerprint')==signature and (saved.get('state')=='ready' or time.time()-saved.get('checked_at',0)<300)
                if not valid and available and probed<2:
                    before=signature
                    try:
                        entry=probe(path)
                        if fingerprint(path)!=before:raise ValueError('File changed during probe')
                    except (OSError,ValueError,subprocess.SubprocessError):entry={'state':'unavailable','video_bps':None,'total_bps':None}
                    saved=cache[ident]={**entry,'fingerprint':signature,'checked_at':time.time()}
                    valid=True;probed+=1
                if valid:entry={k:saved.get(k) for k in ('state','video_bps','total_bps')}
                else:entry['state']='pending';pending=True
            results.append({'name':name,'size':size,**entry})
        if probed:
            if len(cache)>10000:cache=dict(sorted(cache.items(),key=lambda pair:pair[1].get('checked_at',0),reverse=True)[:10000])
            atomic(cache_path,json.dumps(cache))
    return {'files':results,'pending':pending}
