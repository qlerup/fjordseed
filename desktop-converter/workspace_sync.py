"""Report only the selected PC folder over the existing token connection."""
import json
import os
from pathlib import Path, PurePosixPath
import queue
import threading
import urllib.parse
import urllib.request

from remote_agent import NoRedirect, WorkerError, connection_details

VIDEO={'.mkv','.mp4','.m4v','.avi','.mov','.ts','.m2ts','.webm'}


def inventory(folder):
    if not folder:return [],False
    root=Path(folder)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError('Den valgte mappe er ikke tilgængelig.')
    files=[];budget=0
    def fail(error):raise error
    for directory,dirs,names in os.walk(root,followlinks=False,onerror=fail):
        base=Path(directory)
        dirs[:]=sorted(d for d in dirs if not d.startswith('.') and d!='Seeder'
            and not (base/d).is_symlink() and not (base/d).is_junction())
        for name in sorted(names):
            path=base/name
            if name.startswith('.') or path.suffix.lower() not in VIDEO or path.is_symlink():continue
            relative=path.relative_to(root).as_posix()
            entry={'name':relative,'size':path.stat().st_size}
            budget+=len(json.dumps(entry).encode('utf-8'))
            if len(files)>=5000 or budget>2500000:return files,True
            files.append(entry)
    return files,False


def selected_file(command, folder):
    """Resolve metadata to an existing shared file. Never copy or open its data."""
    if not isinstance(command,dict) or command.get('media_folder')!=folder or not folder:
        raise ValueError('Mappevalget matcher ikke beskeden fra FjordSeed.')
    name=command.get('name')
    if (not isinstance(name,str) or not name or len(name)>2048 or
            '\\' in name or any(c in name for c in ':*?"<>|') or any(ord(c)<32 for c in name) or
            PurePosixPath(name).is_absolute() or str(PurePosixPath(name))!=name or
            any(p in ('.','..') or p.startswith('.') for p in name.split('/')) or
            PurePosixPath(name).suffix.lower() not in VIDEO):
        raise ValueError('FjordSeed sendte et ugyldigt filvalg.')
    root=Path(folder)
    if not root.is_absolute():raise ValueError('Vælg en absolut mappesti.')
    path=root
    for part in ('',*name.split('/')):
        if part:path=path/part
        if path.is_symlink() or path.is_junction():
            raise ValueError('Den valgte fil må ikke følge links til andre mapper.')
    if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise ValueError('Filen ligger uden for den valgte mappe.')
    if not path.is_file() or type(command.get('size')) is not int or path.stat().st_size!=command['size']:
        raise ValueError('Filen er ændret eller findes ikke længere i den valgte mappe.')
    return path


def sync_folder(connection_path, preferences_path, receipt=None, receive=None):
    from windows_secret import unprotect
    connection=json.loads(Path(connection_path).read_text(encoding='utf-8'))
    try:preferences=json.loads(Path(preferences_path).read_text(encoding='utf-8'))
    except FileNotFoundError:preferences={}
    folder=preferences.get('media_folder','')
    server,token=connection_details(connection.get('server',''),unprotect(connection['token_dpapi']))
    parsed=urllib.parse.urlsplit(server)
    if (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/') or
            not token.startswith('fsw_')):
        raise ValueError('Kontrollér forbindelseskoden under Indstillinger.')
    files,truncated=inventory(folder)
    payload=json.dumps({'version':1,'media_folder':folder,'files':files,'truncated':truncated,
                        **({'selection_result':receipt} if receipt else {})}).encode('utf-8')
    request=urllib.request.Request(server.rstrip('/')+'/api/conversion/worker/workspace',
        data=payload,method='POST',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with opener.open(request,timeout=10) as response:
        result=json.loads(response.read(65537))
    if result.get('ok') is not True or result.get('media_folder')!=folder:
        raise WorkerError('FjordSeed bekræftede ikke mappevalget.')
    if receive:receive(result.get('selection'),folder)
    return folder


class WorkspaceSync:
    def __init__(self,connection_path,preferences_path):
        self.connection_path,self.preferences_path=connection_path,preferences_path
        self.messages=queue.SimpleQueue()
        self.stopped=threading.Event()
        self.changed=threading.Event()
        self.receipt=None
        self.selection_id=None
        self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            self.changed.clear()
            try:
                folder=sync_folder(self.connection_path,self.preferences_path,self.receipt,self.receive)
                self.messages.put(('ok',folder))
            except (OSError,ValueError,KeyError,WorkerError):
                self.messages.put(('error','Mappevalget er gemt på pc’en. Venter på forbindelse til FjordSeed.'))
            self.changed.wait(5)

    def receive(self, command, folder):
        current=json.loads(Path(self.preferences_path).read_text(encoding='utf-8')) if Path(self.preferences_path).exists() else {}
        if current.get('media_folder','')!=folder:return
        if not command:
            if self.selection_id:
                self.messages.put(('selection_cleared',''))
                self.selection_id=None;self.receipt=None
            return
        ident=command.get('id')
        if not isinstance(ident,str) or len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):
            raise WorkerError('Ugyldig besked om filvalg fra FjordSeed.')
        if command.get('state') not in ('queued','selected'):
            self.messages.put(('selection_cleared',command.get('detail','Filvalget er annulleret.')))
            self.selection_id=None;self.receipt=None
            return
        if ident==self.selection_id:return
        try:
            path=selected_file(command,folder)
            self.messages.put(('selected',{'id':ident,'folder':folder,'path':str(path)}))
            self.receipt={'id':ident,'state':'selected'}
        except (OSError,ValueError):
            detail='Filen kan ikke vælges. Kontrollér netværksmappen og opdatér listen i FjordSeed.'
            self.messages.put(('selection_cleared',detail))
            self.receipt={'id':ident,'state':'error','detail':detail}
        self.selection_id=ident
        self.changed.set()  # Acknowledge promptly; retry safely if the response is lost.

    def close(self):
        self.stopped.set()
        self.changed.set()
