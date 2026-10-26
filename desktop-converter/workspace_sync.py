"""Report only the selected PC folder over the existing token connection."""
import json
import os
from pathlib import Path
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


def sync_folder(connection_path, preferences_path):
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
    payload=json.dumps({'version':1,'media_folder':folder,'files':files,'truncated':truncated}).encode('utf-8')
    request=urllib.request.Request(server.rstrip('/')+'/api/conversion/worker/workspace',
        data=payload,method='POST',headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with opener.open(request,timeout=10) as response:
        result=json.loads(response.read(65537))
    if result.get('ok') is not True or result.get('media_folder')!=folder:
        raise WorkerError('FjordSeed bekræftede ikke mappevalget.')
    return folder


class WorkspaceSync:
    def __init__(self,connection_path,preferences_path):
        self.connection_path,self.preferences_path=connection_path,preferences_path
        self.messages=queue.SimpleQueue()
        self.stopped=threading.Event()
        self.changed=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start()

    def run(self):
        while not self.stopped.is_set():
            self.changed.clear()
            try:
                folder=sync_folder(self.connection_path,self.preferences_path)
                self.messages.put(('ok',folder))
            except (OSError,ValueError,KeyError,WorkerError):
                self.messages.put(('error','Mappevalget er gemt på pc’en. Venter på forbindelse til FjordSeed.'))
            self.changed.wait(15)

    def close(self):
        self.stopped.set()
        self.changed.set()
