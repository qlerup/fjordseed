"""Encode directly on the selected share, then request server-owned publication."""
from contextlib import contextmanager
import json
import hashlib
import os
from pathlib import Path, PurePosixPath
import threading
import time
import urllib.error

from remote_agent import atomic
from workspace_sync import selected_file, worker_request


def source_signature(path):
    # Shared protocol with shared_library.source_signature; sample only 3 MiB.
    size=Path(path).stat().st_size
    digest=hashlib.sha256(str(size).encode())
    with Path(path).open('rb') as handle:
        for offset in sorted({0,max(0,size//2-524288),max(0,size-1048576)}):
            handle.seek(offset);digest.update(str(offset).encode());digest.update(handle.read(1048576))
    return digest.hexdigest()


def work_paths(command,folder):
    ident=command['id']
    expected=f'.fjordseed-shared/{ident}/.fjordseed-conversion'
    if command.get('work')!=expected or command.get('media_folder')!=folder:
        raise ValueError('Arbejdsmappe og netværksmappe matcher ikke jobbet.')
    output=command.get('output')
    if (not isinstance(output,str) or not output or '\\' in output or
            any(c in output for c in ':*?"<>|') or any(ord(c)<32 for c in output) or
            PurePosixPath(output).is_absolute() or str(PurePosixPath(output))!=output or
            any(p in ('.','..') or p.startswith('.') for p in output.split('/')) or
            PurePosixPath(output).suffix.lower()!='.mkv'):
        raise ValueError('Ugyldig resultatsti.')
    root=Path(folder)
    work=root.joinpath(*expected.split('/'))
    target=work/'result'/Path(output)
    for path in (work,target,*target.parents):
        if path==root.parent:break
        if path.is_symlink() or path.is_junction():raise ValueError('Arbejdsstier må ikke følge links.')
    if not work.is_dir() or not target.parent.is_dir():raise ValueError('FjordSeeds arbejdsmappe mangler.')
    return work,target


@contextmanager
def exclusive(work):
    with (work/'worker.lock').open('a+b') as handle:
        handle.seek(0);handle.write(b'0');handle.flush();handle.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            if os.name=='nt':
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)


class SharedRunner:
    def __init__(self,connection_path,preferences_path,convert,cancelled,messages,changed):
        self.connection_path,self.preferences_path=connection_path,preferences_path
        self.convert,self.cancelled=convert,cancelled
        self.messages,self.changed=messages,changed
        self.stop=threading.Event();self.thread=None;self.receipt=None
        self.key=None;self.can_cancel=False
        self.terminal=None
        self.command=None

    @property
    def busy(self):return bool(self.thread and self.thread.is_alive())

    def accept(self,command,folder):
        key=(command['id'],command.get('attempt'))
        if self.busy:return
        if command.get('state') in ('completed','error','cancelled'):
            terminal=(key,command['state'])
            if terminal!=self.terminal:
                self.messages.put(('job_done',command) if command['state']=='completed' else ('job_error',command.get('detail') or 'Jobbet er stoppet. Originalerne er bevaret.'))
            self.key=key;self.terminal=terminal;return
        if key==self.key:return
        if command.get('bitrate') not in (20,30,40):raise ValueError('Ugyldig videokvalitet.')
        self.key=key;self.command=command;self.stop.clear()
        self.thread=threading.Thread(target=self.run,args=(command,folder),daemon=True)
        self.thread.start()

    def cancel(self):
        if self.busy:self.stop.set();return
        if not self.command:return
        def finish():
            try:
                self.request(self.command,'POST','cancel')
                self.receipt=None
                self.messages.put(('job_error','Konverteringen er afbrudt. Originalerne er bevaret.'))
            except (OSError,ValueError):self.messages.put(('job_error','Jobbet kunne ikke afbrydes. Kontrollér forbindelsen til FjordSeed.'))
            self.changed.set()
        self.thread=threading.Thread(target=finish,daemon=True);self.thread.start()

    def request(self,command,method='GET',action=None):
        return worker_request(self.connection_path,method,'/shared/'+command['id'],
                              {'action':action} if action else None,timeout=620 if action=='complete' else 15)

    def watch(self,command,result):
        while not self.stop.is_set():
            if result.get('state')=='completed':
                self.receipt=None;self.messages.put(('job_done',result));self.changed.set();return
            if result.get('state')=='error':raise ValueError(result.get('detail','FjordSeed kunne ikke færdiggøre jobbet.'))
            self.messages.put(('job_status',result.get('detail') or 'Afventer flytning af originaltorrent og publicering …'))
            if self.stop.wait(3):return
            try:result=self.request(command)
            except (OSError,ValueError):continue

    def run(self,command,folder):
        work=None;self.can_cancel=True;last_write=0
        ident=command['id']
        def notify(kind,value):
            nonlocal last_write
            if kind=='status':self.messages.put(('job_status',value))
            if kind=='progress':
                percent,fps,remaining=value
                self.receipt={'id':ident,'state':'converting','progress':round(percent,1),'detail':'Konverterer på pc’ens NVIDIA-GPU'}
                self.messages.put(('job_progress',value))
                if work and time.monotonic()-last_write>1:
                    atomic(work/'status.json',{'id':ident,'state':'encoding','progress':round(percent,1),'detail':self.receipt['detail']})
                    last_write=time.monotonic()
        try:
            while not self.stop.is_set():
                try:initial=self.request(command);break
                except (OSError,ValueError):
                    if self.stop.wait(5):return
            else:return
            if initial.get('state')=='completed' or initial.get('phase')=='moving' or initial.get('state')=='ready':
                self.can_cancel=False;self.watch(command,initial);return
            current=json.loads(Path(self.preferences_path).read_text(encoding='utf-8'))
            if current.get('media_folder')!=folder:raise ValueError('Mappevalget er ændret.')
            source=selected_file(command,folder)
            if source_signature(source)!=command.get('source_signature'):
                raise ValueError('Pc’ens kildefil matcher ikke serverens torrentfil.')
            work,target=work_paths(command,folder)
            self.receipt={'id':ident,'state':'converting','progress':0,'detail':'Starter GPU-konvertering'}
            self.messages.put(('job_start',{'path':str(source),'bitrate':command['bitrate']}));self.changed.set()
            with exclusive(work):
                atomic(work/'client-run.json',{'id':ident,'attempt':command['attempt']})
                if not target.exists():
                    # Only disposable outputs in this server-created job are removed on retry.
                    target.with_suffix('.partial.mkv').unlink(missing_ok=True)
                    target.with_suffix('.log').unlink(missing_ok=True)
                    self.convert(source,target.parent,command['bitrate'],notify,self.stop,target_name=target.name)
                else:
                    report=json.loads(target.with_suffix('.json').read_text(encoding='utf-8'))
                    if report.get('verified') is not True or report.get('video_mbps_target')!=command['bitrate']:
                        raise ValueError('En eksisterende resultatfil kan ikke genbruges.')
                if self.stop.is_set():raise self.cancelled()
                atomic(work/'status.json',{'id':ident,'state':'encoded','progress':100,'detail':'Pc-konvertering kontrolleret · afventer FjordSeed'})
            self.can_cancel=False
            self.messages.put(('job_status','FjordSeed kontrollerer resultatet og flytter hele originaltorrenten til Seeder …'))
            while not self.stop.is_set():
                try:
                    result=self.request(command,'POST','complete')
                    break
                except urllib.error.HTTPError as exc:
                    if exc.code not in (423,503):raise
                except (OSError,ValueError):pass
                if self.stop.wait(5):return
            else:return
            self.watch(command,result)
        except self.cancelled:
            try:self.request(command,'POST','cancel')
            except (OSError,ValueError):pass
            self.receipt={'id':ident,'state':'error','detail':'Konverteringen blev afbrudt. Originalerne er bevaret.'}
            self.messages.put(('job_error',self.receipt['detail']));self.changed.set()
        except Exception as exc:
            detail=(str(exc) if isinstance(exc,(ValueError,RuntimeError)) and str(exc) else
                'Konverteringen kunne ikke fuldføres. Originalerne er bevaret. Se jobbets log i netværksmappen.')[:300]
            self.receipt={'id':ident,'state':'error','detail':detail}
            if work and work.is_dir():
                try:atomic(work/'status.json',{'id':ident,'state':'error','progress':0,'detail':detail})
                except OSError:pass
            self.messages.put(('job_error',detail));self.changed.set()
        finally:self.can_cancel=False
