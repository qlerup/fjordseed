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


def estimate_sizes(duration, video_bps, total_bps, source_size):
    """VBR targets, decimal Mbps; preserve all other streams plus mux overhead.

    No duration or no separate video rate means unknown, never a fabricated size.
    FLAC depends on decoded sample entropy and cannot promise a saving.
    """
    estimates={}
    for rate in (20,30,40):
        size=None
        if duration and video_bps and total_bps and total_bps>=video_bps:
            size=round(duration*(rate*1_000_000+total_bps-video_bps)/8*1.01)
        estimates[str(rate)]={'estimated_bytes':size,
            'saved_bytes':source_size-size if size is not None else None,
            'approximate':True,'reason':None if size is not None else 'Varighed eller videobitrate mangler'}
    estimates['audio']={'estimated_bytes':None,'saved_bytes':None,'approximate':True,
        'reason':'Størrelsen på tabsfri lyd afhænger af lyden. Video kopieres; Atmos/DTS:X-spor bevares uændret.'}
    return estimates


def probe(path):
    result=subprocess.run(['ffprobe','-v','error','-show_entries',
        'stream=index,codec_type,codec_name,profile,channels,channel_layout,sample_rate,bit_rate:stream_disposition:stream_side_data:stream_tags:format=bit_rate,duration',
        '-of','json',str(path)],capture_output=True,text=True,check=True,timeout=2)
    data=json.loads(result.stdout);streams=data.get('streams') or []
    stream=next((s for s in streams if s.get('codec_type')=='video' and not s.get('disposition',{}).get('attached_pic')),streams[0] if streams else {})
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
    dv=next((s for s in stream.get('side_data_list',[]) if s.get('side_data_type')=='DOVI configuration record'),None)
    profile=dv.get('dv_profile') if dv else None
    compatibility=dv.get('dv_bl_signal_compatibility_id') if dv else None
    label=(str(profile)+('.'+str(compatibility) if profile==8 and compatibility is not None else '')) if profile is not None else None
    estimates=estimate_sizes(duration,video,total,path.stat().st_size)
    from conversion_media import audio_plan, audio_description
    tracks=[]
    for index,audio in enumerate(s for s in streams if s.get('codec_type')=='audio'):
        try:track=audio_plan({'streams':[audio]})[0]
        except ValueError as exc:
            track={'codec':audio.get('codec_name'),'output_codec':None,'action':'unsupported',
                'stream_index':audio.get('index'),'channels':audio.get('channels'),
                'channel_layout':audio.get('channel_layout'),'language':audio.get('tags',{}).get('language','und'),
                'title':audio.get('tags',{}).get('title',''),'description':audio_description(audio),
                'profile':audio.get('profile'),'error':str(exc)}
        tracks.append({**track,'index':index})
    audio_error=None if tracks else 'Filen har ingen lydspor.'
    return {'duration_seconds':duration,'audio_tracks':tracks,'audio_error':audio_error,'estimates':estimates,'video_bps':video,'total_bps':total,'state':'ready' if data.get('streams') or total else 'unavailable',
            'dolby_vision':bool(dv) if data.get('streams') else None,'dolby_vision_profile':label,
            'dolby_vision_supported':(profile==7 or (profile==8 and compatibility==1)) if dv else None}


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
        dirs[:]=[d for d in dirs if not d.startswith('.') and d!='Seeder'
                 and not (Path(folder)==root and d=='Originals') and not (Path(folder)/d).is_symlink()]
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
                valid=saved.get('scan_version')==4 and saved.get('fingerprint')==signature and (saved.get('state')=='ready' or time.time()-saved.get('checked_at',0)<300)
                if not valid and available and probed<2:
                    before=signature
                    try:
                        entry=probe(path)
                        if fingerprint(path)!=before:raise ValueError('File changed during probe')
                    except (OSError,ValueError,subprocess.SubprocessError):entry={'state':'unavailable','video_bps':None,'total_bps':None}
                    saved=cache[ident]={**entry,'fingerprint':signature,'checked_at':time.time(),'scan_version':4}
                    valid=True;probed+=1
                if valid:entry={k:saved.get(k) for k in ('state','video_bps','total_bps','dolby_vision','dolby_vision_profile','dolby_vision_supported','duration_seconds','audio_tracks','audio_error','estimates')}
                else:entry['state']='pending';pending=True
            results.append({'name':name,'size':size,**entry})
        if probed:
            if len(cache)>10000:cache=dict(sorted(cache.items(),key=lambda pair:pair[1].get('checked_at',0),reverse=True)[:10000])
            atomic(cache_path,json.dumps(cache))
    return {'files':results,'pending':pending}
