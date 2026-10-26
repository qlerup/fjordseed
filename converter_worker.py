"""Single GPU filesystem worker. Install beside NVEncC on the GPU host.

Only configured .incomplete buffers are mounted writable. Library publication
and original deletion belong exclusively to FjordSeed/qBittorrent.
"""
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
import tempfile
import sys
from collections import Counter
from fractions import Fraction

from conversion import DIRECTORY, HEARTBEAT, checked, safe_relative
from state import atomic

LOG=logging.getLogger(__name__)
STOP=threading.Event()
VIDEO={'.mkv','.mp4','.m4v','.avi','.mov','.ts','.m2ts','.webm'}


def probe(path):
    result=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-show_chapters',
                           '-of','json',str(path)],capture_output=True,text=True,check=True,timeout=120)
    data=json.loads(result.stdout)
    frames=subprocess.run(['ffprobe','-v','error','-threads','1','-select_streams','v:0',
        '-read_intervals','0%+#3','-show_frames','-show_entries','frame_side_data','-of','json',str(path)],
        capture_output=True,text=True,check=True,timeout=120)
    video=next(s for s in data['streams'] if s['codec_type']=='video')
    sides=video.setdefault('side_data_list',[])
    present={s['side_data_type'] for s in sides}
    data['_rpu_frames']=0
    for frame in json.loads(frames.stdout).get('frames',[]):
        for side in frame.get('side_data_list',[]):
            kind=side.get('side_data_type')
            if kind=='Dolby Vision RPU Data':data['_rpu_frames']+=1
            if kind in ('Mastering display metadata','Content light level metadata') and kind not in present:
                sides.append(side);present.add(kind)
    return data


def video(data):
    streams=[s for s in data['streams'] if s['codec_type']=='video' and not s.get('disposition',{}).get('attached_pic')]
    if len(streams)!=1:
        raise ValueError('Filen skal have ét almindeligt videospor; originalen beholdes.')
    return streams[0]


def dovi(data):
    return next((s for s in video(data).get('side_data_list',[]) if s.get('side_data_type')=='DOVI configuration record'),{})


def command(source,target,bitrate,data):
    v=video(data)
    dv=dovi(data)
    if dv and not (dv.get('dv_profile')==7 or (dv.get('dv_profile')==8 and dv.get('dv_bl_signal_compatibility_id')==1)):
        raise ValueError('Denne Dolby Vision-profil understøttes ikke; originalen beholdes.')
    depth='10' if '10' in v.get('pix_fmt','') or dv or v.get('color_transfer') in ('smpte2084','arib-std-b67') else '8'
    if v.get('pix_fmt') not in ('yuv420p','yuv420p10le'):
        raise ValueError('Videoens farveformat understøttes ikke; originalen beholdes.')
    args=['nvencc','--avsw','-i',str(source),'-o',str(target),'-c','hevc',
          '--profile','main10' if depth=='10' else 'main','--output-depth',depth,'--preset','quality',
          '--vbr',str(bitrate*1000),'--max-bitrate',str(bitrate*1500),'--vbv-bufsize',str(bitrate*1500),
          '--colormatrix','auto','--transfer','auto','--colorprim','auto','--chromaloc','auto',
          '--audio-copy','--audio-metadata','copy','--audio-disposition','copy',
          '--sub-copy','--sub-metadata','copy','--sub-disposition','copy','--attachment-copy','--metadata','copy',
          '--chapter-copy','--avsync','vfr']
    if v.get('color_transfer')=='smpte2084':args+=['--max-cll','copy','--master-display','copy']
    if dv:args+=['--dolby-vision-profile','8.1','--dolby-vision-rpu','copy']
    return args


def validate(original,result):
    before,after=video(original),video(result)
    for field in ('width','height','pix_fmt','color_transfer','color_primaries','color_space'):
        if before.get(field)!=after.get(field):
            raise ValueError('Kontrol fejlede: videoens '+field+' blev ændret.')
    a,b=Fraction(before['avg_frame_rate']),Fraction(after['avg_frame_rate'])
    if abs(float(a-b))>.01:raise ValueError('Billedhastigheden blev ændret.')
    if abs(float(original['format']['duration'])-float(result['format']['duration']))>3:
        raise ValueError('Kontrol fejlede: varigheden blev ændret.')
    def duration(data):
        stream=video(data)
        tag=stream.get('tags',{}).get('DURATION','').split(':')
        if len(tag)==3:return sum(float(x)*m for x,m in zip(tag,(3600,60,1)))
        return float(stream.get('duration',data['format']['duration']))
    if abs(duration(original)-duration(result))>3:
        raise ValueError('Kontrol fejlede: videospor er afkortet.')
    def tracks(data,kind):
        return Counter((s.get('codec_name'),s.get('tags',{}).get('language','und'),s.get('channels'),
                        s.get('tags',{}).get('title',''),s.get('disposition',{}).get('default',0),s.get('disposition',{}).get('forced',0))
                       for s in data['streams'] if s['codec_type']==kind)
    for kind in ('audio','subtitle','attachment'):
        if tracks(original,kind)!=tracks(result,kind):raise ValueError('Kontrol fejlede: '+kind+'-spor ændret.')
    if len(original.get('chapters',[]))!=len(result.get('chapters',[])):
        raise ValueError('Kontrol fejlede: kapitler mangler.')
    for old,new in zip(original.get('chapters',[]),result.get('chapters',[])):
        if abs(float(old['start_time'])-float(new['start_time']))>.1 or old.get('tags',{}).get('title')!=new.get('tags',{}).get('title'):
            raise ValueError('Kontrol fejlede: kapitler ændret.')
    required={s['side_data_type'] for s in before.get('side_data_list',[])} & {'Mastering display metadata','Content light level metadata'}
    if not required <= {s['side_data_type'] for s in after.get('side_data_list',[])}:
        raise ValueError('Kontrol fejlede: HDR-metadata mangler.')
    if dovi(original):
        dv=dovi(result)
        if not (dv.get('dv_profile')==8 and dv.get('dv_bl_signal_compatibility_id')==1 and result.get('_rpu_frames')):
            raise ValueError('Kontrol fejlede: Dolby Vision 8.1/RPU mangler.')


def report(work,ident,state,detail,progress=0):
    atomic(checked(work/'status.json'),json.dumps({'id':ident,'state':state,'detail':detail,
           'progress':round(progress,1),'at':time.time()}),mode=0o644)


def restore_flags(original,target):
    # NVEncC's unqualified disposition copy may apply the first track's flags
    # to all tracks. Correct MKV headers in place, without remuxing DV video.
    args=['mkvpropedit',str(target)]
    for kind,prefix in (('audio','a'),('subtitle','s')):
        for index,stream in enumerate((s for s in original['streams'] if s['codec_type']==kind),1):
            args+=['--edit',f'track:{prefix}{index}','--set','flag-default='+str(stream.get('disposition',{}).get('default',0)),
                   '--set','flag-forced='+str(stream.get('disposition',{}).get('forced',0))]
    # Rebuild statistics instead of retaining the original video's old bitrate.
    args+=['--add-track-statistics-tags']
    result=subprocess.run(args,capture_output=True,text=True,timeout=1800,env={**os.environ,'LC_ALL':'C.UTF-8'})
    if result.returncode not in (0,1):raise ValueError('MKV-metadata kunne ikke bevares; originalen beholdes.')


def run_job(work):
    work=checked(work)
    request=json.loads(checked(work/'request.json').read_text())
    if request.get('executor','server')!='server':return
    ident=request.get('id','')
    if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('Invalid job identity')
    try:
        if request.get('version')!=1 or type(request.get('bitrate')) is not int or request['bitrate'] not in (10,15,20,25,30,40):
            raise ValueError('Ugyldige konverteringsindstillinger.')
        files=request.get('files')
        if not isinstance(files,list) or not 1<=len(files)<=10000:raise ValueError('Ugyldig filliste.')
        names=[str(safe_relative(f['name'])) for f in files]
        if len(set(n.casefold() for n in names))!=len(names):raise ValueError('Filnavne kolliderer.')
        outputs=[str(Path(n).with_suffix('.mkv')) if Path(n).suffix.lower() in VIDEO else n for n in names]
        if len(set(n.casefold() for n in outputs))!=len(outputs):raise ValueError('Konverterede filnavne kolliderer.')
        if not any(Path(n).suffix.lower() in VIDEO for n in names):raise ValueError('Torrenten indeholder ingen understøttede videofiler.')
        total=0
        for f in files:
            source=checked(work.parent/f['name'])
            if not source.is_file() or source.stat().st_size!=f['size']:raise ValueError('Originalfilen mangler eller er ændret.')
            total+=f['size']
        # Conservative reserve for a second copy; partial output is never published.
        if shutil.disk_usage(work).free < total+1024**3:
            report(work,ident,'waiting_space','Venter på plads til konverteringen. Originalen beholdes.');return
        result=checked(work/'result');result.mkdir(exist_ok=True)
        log=checked(work/'encoder.log')
        for index,(entry,name) in enumerate(zip(files,outputs)):
            if STOP.is_set():return
            source=checked(work.parent/entry['name']);target=checked(result/name)
            target.parent.mkdir(parents=True,exist_ok=True)
            # On restart re-validate completed files, never assume length means success.
            if source.suffix.lower() in VIDEO:
                original=probe(source)
                if target.exists():
                    validate(original,probe(target));continue
                scratch=checked(work/'scratch');scratch.mkdir(exist_ok=True)
                partial=checked(scratch/(str(index)+'.mkv'))
                partial.unlink(missing_ok=True)
                report(work,ident,'encoding','GPU-konvertering: '+entry['name'],index/len(files)*100)
                expected=max(1,float(original['format']['duration'])*float(Fraction(video(original)['avg_frame_rate'])))
                with log.open('a',encoding='utf-8') as handle:
                    process=subprocess.Popen(command(source,partial,request['bitrate'],original),
                        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',start_new_session=True)
                    def cancel():
                        while process.poll() is None:
                            if STOP.wait(1):
                                try:os.killpg(process.pid,signal.SIGTERM)
                                except ProcessLookupError:pass
                                return
                    threading.Thread(target=cancel,daemon=True).start()
                    for line in process.stdout:
                        line=re.sub(r'\x1b\[[0-9;]*[A-Za-z]','',line)
                        handle.write(line);handle.flush()
                        match=re.search(r'\b(\d+)(?:/\d+)? frames:',line)
                        if match:
                            percent=(index+min(.99,int(match[1])/expected))/len(files)*100
                            report(work,ident,'encoding','GPU-konvertering: '+entry['name'],percent)
                    code=process.wait()
                if STOP.is_set():return
                if code:raise ValueError('GPU-konverteringen fejlede (kode '+str(code)+'). Se encoder.log; originalen beholdes.')
                report(work,ident,'verifying','Kontrollerer video, lyd, undertekster, HDR og kapitler',index/len(files)*100)
                restore_flags(original,partial)
                validate(original,probe(partial))
                if source.stat().st_size!=entry['size']:raise ValueError('Originalfilen ændrede sig under konverteringen.')
                partial.rename(target)
            elif not target.exists():
                # Sidecar subtitles/NFO/artwork remain bit-for-bit intact.
                scratch=checked(work/'scratch');scratch.mkdir(exist_ok=True)
                partial=checked(scratch/(str(index)+'.sidecar'))
                shutil.copyfile(source,partial);partial.rename(target)
        atomic(result/'.fjordseed-converted.json',json.dumps({'id':ident,'files':outputs}),mode=0o644)
        report(work,ident,'ready','Kontrolleret · klar til biblioteket',100)
    except Exception as exc:
        LOG.exception('Conversion failed for %s',ident)
        report(work,ident,'error',str(exc) if isinstance(exc,ValueError) else 'Konverteringen fejlede. Se worker-loggen; originalen beholdes.')


def run():
    import fcntl
    check_gpu()
    buffers=[checked(Path(p)) for p in os.environ['FJORDSEED_BUFFERS'].split(':')]
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:STOP.set())
    lock=Path('/run/fjordseed-converter/worker.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    def heartbeat():
        while not STOP.is_set():
            for root in buffers:
                try:atomic(checked(root/HEARTBEAT),json.dumps({'version':1,'at':time.time()}),mode=0o644)
                except OSError:LOG.exception('Buffer unavailable')
            STOP.wait(5)
    threading.Thread(target=heartbeat,daemon=True).start()
    # Interrupted jobs are resumed from verified per-file outputs after restart.
    while not STOP.is_set():
        for root in buffers:
            for request in sorted(root.glob('*/'+DIRECTORY+'/request.json')):
                try:
                    status_path=checked(request.parent/'status.json')
                    status=json.loads(status_path.read_text()) if status_path.exists() else {}
                    if status.get('state') in ('ready','error'):continue
                    # Shared lock also prevents two installations sharing a buffer
                    # from ever processing the same request concurrently.
                    with checked(request.parent/'worker.lock').open('a') as job_lock:
                        try:fcntl.flock(job_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        except BlockingIOError:continue
                        latest=json.loads(status_path.read_text()) if status_path.exists() else {}
                        if latest.get('state') in ('ready','error'):continue
                        run_job(request.parent)
                except Exception:LOG.exception('Could not read conversion request')
                if STOP.is_set():return
        STOP.wait(5)


def check_gpu():
    """Actual HEVC encode, not just device enumeration; no network or media access."""
    with tempfile.TemporaryDirectory() as directory:
        source=Path(directory)/'source.mkv';target=Path(directory)/'result.mkv'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=s=256x144:r=24:d=0.5',
                        '-c:v','ffv1',str(source)],check=True,capture_output=True,timeout=30)
        original=probe(source)
        subprocess.run(command(source,target,20,original),check=True,capture_output=True,timeout=60)
        result=probe(target)
        if video(result).get('codec_name')!='hevc':raise ValueError('GPU test failed')
    print('NVEncC HEVC GPU test passed',flush=True)


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    check_gpu() if '--check-gpu' in sys.argv else run()
