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


def report(work,ident,state,detail,progress=0,*,stage=None,eta_seconds=None):
    now=time.time()
    try:previous=json.loads(checked(work/'status.json').read_text())
    except (OSError,ValueError):previous={}
    if not isinstance(previous,dict):previous={}
    stage=stage or {'encoded':'server_verifying','ready':'publishing'}.get(state,state)
    started=previous.get('stage_started_at') if previous.get('stage')==stage and previous.get('id')==ident else now
    atomic(checked(work/'status.json'),json.dumps({'id':ident,'state':state,'detail':detail,
           'progress':round(progress,1),'at':now,'stage':stage,'stage_started_at':started or now,
           'phase_progress':round(progress,1) if state=='encoding' else None,
           'eta_seconds':eta_seconds}),mode=0o644)


def audio_progress(line, duration, elapsed):
    if not line.startswith('out_time_us='): return None
    try:
        processed = float(line.split('=',1)[1]) / 1_000_000
        duration = float(duration)
    except (ValueError, TypeError): return None
    if not all(math.isfinite(v) for v in (processed, duration, elapsed)) or duration<=0 or processed<0:
        return None
    percent = min(99.9, processed/duration*100)
    # Allow startup to settle before extrapolating an ETA from measured speed.
    eta = max(0, round((duration-processed)*elapsed/processed)) if elapsed>=5 and processed>0 else None
    return percent, eta


def run_job(work):
    work=checked(work)
    request=json.loads(checked(work/'request.json').read_text())
    if request.get('executor','server')!='server':return
    ident=request.get('id','')
    if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('Invalid job identity')
    try:
        from conversion_media import dolby_mode, conversion_mode
        conversion_mode(request.get('conversion_mode','video'))
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
        reserve = total * (2 if request.get('options', {}).get('mode') in ('full', 'video') else 1)
        if shutil.disk_usage(work).free < reserve+1024**3:
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
                if request.get('conversion_mode')=='audio':
                    from conversion_media import output_reserve
                    if shutil.disk_usage(work).free < output_reserve(original,entry['size'],request.get('selected_audio_tracks')):
                        report(work,ident,'waiting_space','Venter på plads til flerkanalslyd. Originalen beholdes.');return
                options = None
                reference = original
                if request.get('options'):
                    from conversion_options import normalize, reference as selected_reference, validate_audio_only, remux_command
                    options = normalize(request['options'], original)
                    reference = selected_reference(original, options)
                if target.exists() and options:
                    if options['mode'] == 'audio': validate_audio_only(reference, probe(target))
                    else: validate_file(reference, target, mode=options['dolby_vision_mode'])
                    continue
                if target.exists():
                    if dovi(original) and dovi(probe(target)):prepare_output(original,target,mode=request.get('dolby_vision_mode','separate'),conversion_mode=request.get('conversion_mode','video'),selected_audio_tracks=request.get('selected_audio_tracks'))
                    validate_file(original,target,mode=request.get('dolby_vision_mode','separate'),conversion_mode=request.get('conversion_mode','video'),selected_audio_tracks=request.get('selected_audio_tracks'));continue
                scratch=checked(work/'scratch');scratch.mkdir(exist_ok=True)
                partial=checked(scratch/(str(index)+'.mkv'))
                partial.unlink(missing_ok=True)
                from dolby_backup import sidecar
                sidecar(partial).unlink(missing_ok=True)
                report(work,ident,'encoding','GPU-konvertering: '+entry['name'],0)
                if not options or options['mode'] != 'audio':
                    expected=max(1,float(original['format']['duration'])*float(Fraction(video(original)['avg_frame_rate'])))
                    with log.open('a',encoding='utf-8') as handle:
                        process=subprocess.Popen(command(source,partial,request['bitrate'],original,reader=select_decoder(video(original),'nvencc') if request.get('conversion_mode','video')=='video' else 'avsw',conversion_mode=request.get('conversion_mode','video'),selected_audio_tracks=request.get('selected_audio_tracks')),
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
                            if request.get('conversion_mode')=='audio' and line.startswith('out_time_us='):
                                try:percent=max(0,min(99,float(line.split('=',1)[1])/1_000_000/float(original['format']['duration'])*100))
                                except ValueError:continue
                                report(work,ident,'encoding','Konverterer lyd: '+entry['name'],percent)
                            match=re.search(r'\b(\d+)(?:/\d+)? frames:',line)
                            if match:
                                percent=min(99,int(match[1])/expected*100)
                                report(work,ident,'encoding','GPU-konvertering: '+entry['name'],percent)
                        code=process.wait()
                    if STOP.is_set():return
                    if code:raise ValueError('GPU-konverteringen fejlede (kode '+str(code)+'). Se encoder.log; originalen beholdes.')
                if options:
                    remuxed=checked(scratch/(str(index)+'.selected.mkv'))
                    remuxed.unlink(missing_ok=True)
                    detail='Tilpasser lyd og valgte spor: '+entry['name']
                    report(work,ident,'encoding',detail,stage='audio_encoding')
                    remux_log=log.open('a')
                    args=remux_command(source, partial if options['mode'] != 'audio' else None,
                        remuxed, original, options)
                    args[1:1]=['-progress','pipe:1','-stats_period','1','-nostats']
                    process=subprocess.Popen(args, stdout=subprocess.PIPE, stderr=remux_log,
                        text=True, errors='replace', start_new_session=True)
                    remux_log.close()
                    def cancel_remux(process=process):
                        while process.poll() is None:
                            if STOP.wait(1):
                                try: os.killpg(process.pid,signal.SIGTERM)
                                except ProcessLookupError: pass
                                return
                    threading.Thread(target=cancel_remux,daemon=True).start()
                    started=time.monotonic()
                    for line in process.stdout:
                        measured=audio_progress(line,original.get('format',{}).get('duration'),time.monotonic()-started)
                        if measured:
                            percent,eta=measured
                            report(work,ident,'encoding',detail,percent,stage='audio_encoding',eta_seconds=eta)
                    process.wait()
                    if STOP.is_set(): return
                    if process.returncode: raise ValueError('Lydkonverteringen fejlede. Originalen beholdes.')
                    partial.unlink(missing_ok=True)
                    remuxed.rename(partial)
                report(work,ident,'verifying','Kontrollerer video, valgte lydspor, kanaler, undertekster og kapitler')
                if options and options['mode'] == 'audio':
                    restore_flags(reference,partial)
                    validate_audio_only(reference,probe(partial))
                else:
                    prepare_output(reference,partial,mode=request.get('dolby_vision_mode','separate'),conversion_mode=request.get('conversion_mode','video'),selected_audio_tracks=request.get('selected_audio_tracks'))
                    validate_file(reference,partial,mode=request.get('dolby_vision_mode','separate'),conversion_mode=request.get('conversion_mode','video'),selected_audio_tracks=request.get('selected_audio_tracks'))
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
                    'video_mbps_target':request['bitrate'],'conversion_mode':request.get('conversion_mode','video'),'selected_audio_tracks':request.get('selected_audio_tracks'),'dolby_vision_mode':request.get('dolby_vision_mode','separate'),'gpu_encoder':'FFmpeg FLAC audio' if request.get('conversion_mode')=='audio' else 'NVEncC server'}),mode=0o644)
        report(work,ident,'encoded' if request.get('shared') else 'ready','Kontrolleret · klar til biblioteket',100)
    except Exception as exc:
        LOG.exception('Conversion failed for %s',ident)
        report(work,ident,'error',str(exc) if isinstance(exc,ValueError) else 'Konverteringen fejlede. Se worker-loggen; originalen beholdes.')


def run():
    import fcntl
    audio_only=os.environ.get('FJORDSEED_AUDIO_ONLY')=='1'
    if not audio_only:check_gpu()
    buffers=[checked(Path(p)) for p in os.environ['FJORDSEED_BUFFERS'].split(':')]
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:STOP.set())
    lock=Path('/run/fjordseed-converter/worker.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    def heartbeat():
        while not STOP.is_set():
            for root in buffers:
                try:atomic(checked(root/('.fjordseed-audio-converter.json' if audio_only else HEARTBEAT)),json.dumps({'version':1,'at':time.time()}),mode=0o644)
                except OSError:LOG.exception('Buffer unavailable')
            STOP.wait(5)
    threading.Thread(target=heartbeat,daemon=True).start()
    # Interrupted jobs are resumed from verified per-file outputs after restart.
    while not STOP.is_set():
        for root in buffers:
            for request in sorted(root.glob('*/'+DIRECTORY+'/request.json')):
                try:
                    if audio_only:
                        data=json.loads(checked(request).read_text())
                        if data.get('options',{}).get('mode',data.get('conversion_mode','video'))!='audio':continue
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
