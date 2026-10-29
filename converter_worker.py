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
from fractions import Fraction

from conversion import DIRECTORY, HEARTBEAT, checked, safe_relative
from state import atomic
from conversion_media import probe, video, dovi, command, validate, restore_flags, prepare_output, validate_file, publish_output
from conversion_decoder import select as select_decoder

LOG=logging.getLogger(__name__)
STOP=threading.Event()
VIDEO={'.mkv','.mp4','.m4v','.avi','.mov','.ts','.m2ts','.webm'}


def report(work,ident,state,detail,progress=0):
    now=time.time()
    try:previous=json.loads(checked(work/'status.json').read_text())
    except (OSError,ValueError):previous={}
    if not isinstance(previous,dict):previous={}
    stage={'encoded':'server_verifying','ready':'publishing'}.get(state,state)
    started=previous.get('stage_started_at') if previous.get('stage')==stage and previous.get('id')==ident else now
    atomic(checked(work/'status.json'),json.dumps({'id':ident,'state':state,'detail':detail,
           'progress':round(progress,1),'at':now,'stage':stage,'stage_started_at':started or now,
           'phase_progress':round(progress,1) if state=='encoding' else None}),mode=0o644)


def run_job(work):
    work=checked(work)
    request=json.loads(checked(work/'request.json').read_text())
    if request.get('executor','server')!='server':return
    ident=request.get('id','')
    if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('Invalid job identity')
    try:
        from conversion_media import dolby_mode
        dolby_mode(request.get('dolby_vision_mode','separate'))
        if request.get('version')!=1 or type(request.get('bitrate')) is not int or request['bitrate'] not in (10,15,20,25,30,40):
            raise ValueError('Ugyldige konverteringsindstillinger.')
        files=request.get('files')
        if not isinstance(files,list) or not 1<=len(files)<=10000:raise ValueError('Ugyldig filliste.')
        names=[str(safe_relative(f['name'])) for f in files]
        if len(set(n.casefold() for n in names))!=len(names):raise ValueError('Filnavne kolliderer.')
        outputs=[str(Path(n).with_suffix('.mkv')) if Path(n).suffix.lower() in VIDEO and f.get('convert',True) else n for n,f in zip(names,files)]
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
            if source.suffix.lower() in VIDEO and entry.get('convert',True):
                report(work,ident,'probing','Undersøger video, HDR, lyd og undertekster: '+entry['name'])
                original=probe(source)
                if target.exists():
                    if dovi(original) and dovi(probe(target)):prepare_output(original,target,mode=request.get('dolby_vision_mode','separate'))
                    validate_file(original,target,mode=request.get('dolby_vision_mode','separate'));continue
                scratch=checked(work/'scratch');scratch.mkdir(exist_ok=True)
                partial=checked(scratch/(str(index)+'.mkv'))
                partial.unlink(missing_ok=True)
                from dolby_backup import sidecar
                sidecar(partial).unlink(missing_ok=True)
                report(work,ident,'encoding','GPU-konvertering: '+entry['name'],0)
                expected=max(1,float(original['format']['duration'])*float(Fraction(video(original)['avg_frame_rate'])))
                with log.open('a',encoding='utf-8') as handle:
                    process=subprocess.Popen(command(source,partial,request['bitrate'],original,reader=select_decoder(video(original),'nvencc')),
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
                            percent=min(99,int(match[1])/expected*100)
                            report(work,ident,'encoding','GPU-konvertering: '+entry['name'],percent)
                    code=process.wait()
                if STOP.is_set():return
                if code:raise ValueError('GPU-konverteringen fejlede (kode '+str(code)+'). Se encoder.log; originalen beholdes.')
                report(work,ident,'metadata','Bevarer HDR og skriver sporoplysninger · dette kan tage flere minutter')
                prepare_output(original,partial,mode=request.get('dolby_vision_mode','separate'))
                report(work,ident,'verifying','Kontrollerer den færdige video, lyd, undertekster, HDR og kapitler')
                validate_file(original,partial,mode=request.get('dolby_vision_mode','separate'))
                if source.stat().st_size!=entry['size']:raise ValueError('Originalfilen ændrede sig under konverteringen.')
                publish_output(partial,target)
            elif not target.exists():
                # Sidecar subtitles/NFO/artwork remain bit-for-bit intact.
                scratch=checked(work/'scratch');scratch.mkdir(exist_ok=True)
                partial=checked(scratch/(str(index)+'.sidecar'))
                shutil.copyfile(source,partial);partial.rename(target)
        atomic(result/'.fjordseed-converted.json',json.dumps({'id':ident,'files':outputs,'bitrate':request['bitrate'],'converted_at':time.time()}),mode=0o644)
        if request.get('shared'):
            for name in outputs:
                atomic((result/name).with_suffix('.json'),json.dumps({'verified':True,
                    'video_mbps_target':request['bitrate'],'dolby_vision_mode':request.get('dolby_vision_mode','separate'),'gpu_encoder':'NVEncC server'}),mode=0o644)
        report(work,ident,'encoded' if request.get('shared') else 'ready','Kontrolleret · klar til biblioteket',100)
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
                    if status.get('state') in ('ready','encoded','error'):continue
                    # Shared lock also prevents two installations sharing a buffer
                    # from ever processing the same request concurrently.
                    with checked(request.parent/'worker.lock').open('a') as job_lock:
                        try:fcntl.flock(job_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        except BlockingIOError:continue
                        latest=json.loads(status_path.read_text()) if status_path.exists() else {}
                        if latest.get('state') in ('ready','encoded','error'):continue
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
        subprocess.run(command(source,target,20,original,reader=select_decoder(video(original),'nvencc')),check=True,capture_output=True,timeout=60)
        result=probe(target)
        if video(result).get('codec_name')!='hevc':raise ValueError('GPU test failed')
    print('NVEncC HEVC GPU test passed',flush=True)


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    check_gpu() if '--check-gpu' in sys.argv else run()
