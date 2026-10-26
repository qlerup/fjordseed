"""Pull-only FjordSeed worker: authenticated, resumable, scoped file transfers."""
import base64
import re
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import encode_core as core

CHUNK=8*1024*1024


class WorkerError(Exception):
    def __init__(self,message,status=0):
        super().__init__(message);self.status=status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def atomic(path,data):
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(data),encoding='utf-8');temp.replace(path)


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(CHUNK),b''):digest.update(block)
    return digest.hexdigest()


def connection_details(server, value):
    """Decode a user-pasted pairing code without contacting any server."""
    value=value.strip()
    if value.startswith('fsp1_'):
        try:
            encoded=value[5:]
            if len(encoded)>4096 or not re.fullmatch(r'[A-Za-z0-9_-]+',encoded):raise ValueError()
            data=json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
            server=data['server'];value=data['token']
            if not isinstance(server,str) or not isinstance(value,str):raise ValueError()
            parsed=urllib.parse.urlsplit(server)
            if (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/')):raise ValueError()
            parsed.port
            if not re.fullmatch(r'fsw_[A-Za-z0-9_-]{1,139}',value):raise ValueError()
        except (ValueError,KeyError,TypeError,UnicodeError):
            raise ValueError('Forbindelseskoden er ugyldig. Kopiér hele koden fra FjordSeed.') from None
    return server,value


class Agent:
    def __init__(self,server,token,cache,lock,convert,cancelled,notify):
        server,token=connection_details(server,token)
        parsed=urllib.parse.urlsplit(server.strip())
        if (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):raise ValueError('Indtast en HTTP(S)-adresse uden login eller token i adressen.')
        if not token.startswith('fsw_') or len(token)>143:raise ValueError('Indsæt pc-tokenet fra FjordSeed.')
        self.server=server.strip().rstrip('/')
        self.token=token
        self.cache=Path(cache).resolve();self.cache.mkdir(parents=True,exist_ok=True)
        self.lock,self.convert,self.cancelled,self.notify=lock,convert,cancelled,notify
        self.stop=threading.Event();self.job_stop=threading.Event();self.busy=False
        self.job=None;self.phase='download';self.progress=0
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def call(self,method,path,payload=None,raw=False,lease=None,timeout=30):
        headers={'Authorization':'Bearer '+self.token}
        if lease:headers['X-Job-Lease']=lease
        if payload is not None and not isinstance(payload,bytes):
            payload=json.dumps(payload).encode();headers['Content-Type']='application/json'
        elif isinstance(payload,bytes):headers['Content-Type']='application/octet-stream'
        req=urllib.request.Request(self.server+'/api/conversion/worker'+path,data=payload,headers=headers,method=method)
        try:
            with self.opener.open(req,timeout=timeout) as response:
                data=response.read(CHUNK+1 if raw else 1024*1024+1)
                if len(data)>(CHUNK if raw else 1024*1024):raise WorkerError('Serverens svar er for stort.')
                if raw:
                    if hashlib.sha256(data).hexdigest()!=response.headers.get('X-Chunk-SHA256'):
                        raise WorkerError('Filblokken blev ikke overført korrekt.')
                    return data
                return json.loads(data)
        except urllib.error.HTTPError as exc:
            raise WorkerError('FjordSeed afviste forespørgslen (HTTP '+str(exc.code)+').',exc.code) from None
        except (urllib.error.URLError,TimeoutError,OSError,ValueError):
            raise WorkerError('Forbindelsen til FjordSeed blev afbrudt.') from None

    def transfer(self,*args,**kwargs):
        for attempt in range(5):
            if self.stop.is_set() or self.job_stop.is_set():raise self.cancelled()
            try:return self.call(*args,**kwargs)
            except WorkerError as exc:
                if exc.status in (401,403,409,413) or attempt==4:raise
                if self.stop.wait(2):raise self.cancelled()

    def check_gpu(self):
        ffmpeg=core.TOOLS['ffprobe'].with_name('ffmpeg.exe')
        with tempfile.TemporaryDirectory(prefix='gpu-check-',dir=self.cache) as folder:
            source=Path(folder)/'source.mkv';target=Path(folder)/'encoded.mkv'
            common={'capture_output':True,'creationflags':subprocess.CREATE_NO_WINDOW,'timeout':45}
            subprocess.run([str(ffmpeg),'-v','error','-f','lavfi','-i','color=s=640x360:r=24:d=0.25',
                            '-c:v','ffv1',str(source)],check=True,**common)
            subprocess.run([str(core.TOOLS['nvencc']),'--avsw','-i',str(source),'-o',str(target),
                            '-c','hevc','--output-depth','10','--profile','main10','--preset','quality','--vbr','2000'],check=True,**common)
            if core.video(core.probe(target)).get('codec_name')!='hevc':raise WorkerError('GPU-testen bestod ikke.')

    def heartbeat(self):
        data={'version':1,'gpu_ready':True}
        if self.job:data.update(job=self.job['id'],lease=self.job['lease'],phase=self.phase,progress=self.progress)
        self.call('POST','/heartbeat',data)

    def renew(self,finished):
        last=time.monotonic()
        while not finished.wait(10):
            try:self.heartbeat();last=time.monotonic()
            except WorkerError as exc:
                if exc.status in (401,403,409) or time.monotonic()-last>60:
                    self.job_stop.set();return

    def run_job(self,job):
        if not isinstance(job.get('id'),str) or len(job['id'])!=32 or any(c not in '0123456789abcdef' for c in job['id']):
            raise WorkerError('Ugyldigt job fra serveren.')
        bitrate=job.get('bitrate')
        if type(bitrate) is not int or bitrate not in (10,15,20,25,30,40):
            raise WorkerError('Ugyldig videobitrate fra FjordSeed.')
        self.notify('settings',{'bitrate':bitrate})
        directory=self.cache/job['id'];directory.mkdir(exist_ok=True)
        state_path=directory/'client-state.json'
        try:state=json.loads(state_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):state={}
        if state.get('files')!=job['files']:
            # Server offsets change between claims; source identity is immutable.
            identity=[{k:f[k] for k in ('name','size','output','video','index')} for f in job['files']]
            if state.get('identity')!=identity or state.get('bitrate')!=job['bitrate']:
                state={'identity':identity,'bitrate':job['bitrate'],'outputs':{}}
                atomic(state_path,state)
        self.job=job;self.job_stop.clear();self.busy=True
        finished=threading.Event()
        threading.Thread(target=self.renew,args=(finished,),daemon=True).start()
        try:
            files=job['files']
            if not isinstance(files,list) or not 1<=len(files)<=10000:raise WorkerError('Ugyldig filliste.')
            for i,entry in enumerate(files):
                index=entry['index']
                if type(index) is not int or index!=i:raise WorkerError('Ugyldig filrækkefølge.')
                if entry.get('verified'):continue
                # No server-supplied directory names are used for local paths.
                name=entry['name'].replace('\\','/').rsplit('/',1)[-1]
                from pathlib import PureWindowsPath
                if (not name or name in ('.','..') or name.rstrip(' .')!=name or PureWindowsPath(name).is_reserved()
                        or any(c in name for c in '<>:"|?*') or any(ord(c)<32 for c in name)):
                    raise WorkerError('Ugyldigt filnavn.')
                filedir=directory/str(index);filedir.mkdir(exist_ok=True)
                source=filedir/name
                if source.is_symlink():raise WorkerError('Cachefilen må ikke være et link.')
                self.phase='download';self.notify('status','Henter '+name)
                current=source.stat().st_size if source.exists() else 0
                if current>entry['size']:raise WorkerError('Cachefilen matcher ikke originalen.')
                if shutil.disk_usage(directory).free<entry['size']-current+1024**3:
                    raise WorkerError('Der er ikke plads til filmen i pc-bufferen.')
                with source.open('ab') as out:
                    while current<entry['size']:
                        block=self.transfer('GET',f'/jobs/{job["id"]}/files/{index}?offset={current}',raw=True,lease=job['lease'])
                        if not block or current+len(block)>entry['size']:raise WorkerError('Filen fra serveren blev afkortet.')
                        out.write(block);out.flush();os.fsync(out.fileno());current+=len(block)
                        self.progress=(i+current/max(entry['size'],1)*.25)/len(files)*100
                        self.notify('progress',self.progress)
                saved=state['outputs'].get(str(index),{})
                target=Path(saved.get('path',''))
                valid=(target.is_absolute() and target.is_relative_to(directory) and target.is_file()
                       and not target.is_symlink() and target.stat().st_size==saved.get('size') and sha(target)==saved.get('sha256'))
                if not valid:
                    if self.stop.is_set() or self.job_stop.is_set():raise self.cancelled()
                    self.phase='encode'
                    self.notify('status','Konverterer '+name+' på NVIDIA-GPU')
                    if entry['video']:
                        notified=[False]
                        def progress(kind,value):
                            if kind=='status' and value.startswith('Konverterer på NVIDIA') and not notified[0]:
                                notified[0]=True;self.notify('started',name)
                            if kind=='progress':
                                self.progress=(i+.25+value[0]/100*.5)/len(files)*100
                                self.notify('progress',self.progress)
                                self.notify('metrics',value)
                        target=self.convert(source,filedir,job['bitrate'],progress,self.job_stop)
                    else:target=source
                    state['outputs'][str(index)]={'path':str(target),'size':target.stat().st_size,'sha256':sha(target)}
                    atomic(state_path,state)
                self.phase='upload';self.notify('status','Sender den færdige fil tilbage til FjordSeed')
                size=target.stat().st_size;offset=entry.get('uploaded',0)
                if type(offset) is not int or not 0<=offset<=size:raise WorkerError('Serverens uploadstatus matcher ikke filen.')
                if not entry.get('verified'):
                    with target.open('rb') as handle:
                        handle.seek(offset)
                        if size==0:self.transfer('PUT',f'/jobs/{job["id"]}/files/{index}?offset=0',b'',lease=job['lease'])
                        while offset<size:
                            block=handle.read(CHUNK)
                            result=self.transfer('PUT',f'/jobs/{job["id"]}/files/{index}?offset={offset}',block,lease=job['lease'])
                            offset+=len(block)
                            if result['offset']!=offset:raise WorkerError('Uploadstatus matcher ikke filen.')
                            self.progress=(i+.75+offset/max(size,1)*.2)/len(files)*100
                            self.notify('progress',self.progress)
                    self.phase='verify';self.notify('status','FjordSeed kontrollerer den returnerede fil')
                    self.transfer('POST',f'/jobs/{job["id"]}/verify',{'index':index,'size':size},lease=job['lease'],timeout=2400)
            self.transfer('POST',f'/jobs/{job["id"]}/complete',{},lease=job['lease'])
            self.notify('status','Færdig · FjordSeed har modtaget og kontrolleret filerne')
            self.notify('progress',100)
            # Only this agent's completed UUID cache is disposable.
            if directory.parent.resolve()==self.cache and not directory.is_symlink():shutil.rmtree(directory)
        except self.cancelled:
            raise
        except WorkerError as exc:
            if exc.status==409:
                try:self.call('POST',f'/jobs/{job["id"]}/fail',{},lease=job['lease'])
                except WorkerError:pass
            raise
        except Exception:
            try:self.call('POST',f'/jobs/{job["id"]}/fail',{},lease=job['lease'])
            except WorkerError:pass
            raise WorkerError('Konverteringen fejlede. Se pc-loggen; originalen er bevaret på serveren.') from None
        finally:
            finished.set();self.job=None;self.busy=False

    def run(self):
        try:
            self.notify('status','Tester pc’ens NVIDIA-GPU …');self.check_gpu()
        except Exception:
            self.notify('error','GPU-testen fejlede. Kontrollér NVIDIA-driver og værktøjerne.');self.notify('finished',None);return
        try:
            while not self.stop.is_set():
                try:
                    self.heartbeat()
                    if not self.lock.acquire(timeout=.2):
                        self.notify('status','Forbundet · afventer den lokale konvertering');self.stop.wait(3);continue
                    try:
                        if self.stop.is_set():break
                        job=self.call('POST','/claim',{})['job']
                        if job:
                            if self.stop.is_set():break
                            self.run_job(job)
                        else:self.notify('status','Forbundet · venter på et konverteringsjob fra FjordSeed')
                    finally:self.lock.release()
                except self.cancelled:
                    if not self.stop.is_set():self.notify('status','Jobbet blev afbrudt. Forbinder igen …')
                except WorkerError as exc:
                    self.notify('error',str(exc))
                    if exc.status in (401,403):break
                if self.stop.wait(5):break
        finally:
            self.notify('finished',None)

    def disconnect(self):
        self.stop.set();self.job_stop.set()
