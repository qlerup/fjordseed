"""Explicit streaming mode and shared folders with the local FjordFlix app."""
import hashlib
import json
from pathlib import PurePosixPath

from state import atomic
from storage import Storage


# Run inside Flix: its app credential stays inside its own container. Only the
# fixed authenticated library API and its bounded response are accessible.
FLIX_REQUEST = r'''
import http.client,json,os
key=os.environ.get('FJORDHUB_API_KEY','')
if not key:raise SystemExit(1)
client=http.client.HTTPConnection('127.0.0.1',8080,timeout=8)
client.request('GET','/api/hub/seed-library',headers={'X-Hub-Key':key})
r=client.getresponse();body=r.read(262145)
if len(body)>262144:raise SystemExit(1)
if r.status!=200:print(json.dumps({'ok':False,'status':r.status}));raise SystemExit(1)
data=json.loads(body)
print(json.dumps(data))
'''


def safe_path(value):
    return (isinstance(value,str) and len(value)<=1024 and value.startswith('/')
            and not any(ord(c)<32 for c in value) and '..' not in PurePosixPath(value).parts
            and str(PurePosixPath(value))==value
            and not any(p in ('.incomplete','.fjordseed-buffer') for p in PurePosixPath(value).parts))


class Streaming:
    def __init__(self,runtime):
        self.runtime=runtime

    def public(self):
        data=self.runtime.state.get().get('streaming',{})
        storage=Storage(self.runtime).public()
        return {'enabled':data.get('enabled',True),'buffer_enabled':storage['streaming_enabled'],
                'move_retained':data.get('move_retained',False),
                'buffer_when_disabled':data.get('buffer_enabled',False),
                'connected':bool(data.get('library_path') and data.get('host_path')==storage['path']),
                'host_path':storage['path'],'library_path':data.get('library_path'),
                'connected_host_path':data.get('host_path')}

    def save(self,enabled,connection=None,buffer_enabled=None,move_retained=None):
        if type(enabled) is not bool:
            raise ValueError('Vælg om streaming skal være slået til.')
        if buffer_enabled is not None and type(buffer_enabled) is not bool:
            raise ValueError('Vælg om buffer skal være slået til.')
        if move_retained is not None and type(move_retained) is not bool:
            raise ValueError('Vælg om tidligere downloads skal flyttes.')
        with self.runtime.state.lock:
            data=self.runtime.state.get()
            data['streaming']={**data.get('streaming',{}),'enabled':enabled,**(connection or {})}
            if buffer_enabled is not None:data['streaming']['buffer_enabled']=buffer_enabled
            if move_retained is not None:data['streaming']['move_retained']=move_retained
            atomic(self.runtime.state.path,json.dumps(data))
            Storage(self.runtime).publish()
        return self.public()

    def flix(self):
        try:
            container=self.runtime.client.containers.get('fjordflix')
            if container.status!='running' or container.labels.get('com.docker.compose.service')!='app':
                raise ValueError()
        except Exception:
            raise ValueError('Start FjordFlix på samme Docker-server for at forbinde appsene.') from None
        return container

    @staticmethod
    def request(container):
        result=container.exec_run(['python','-c',FLIX_REQUEST])
        if result.exit_code:
            raise ValueError('FjordFlix kunne ikke forbinde biblioteket. Opdatér FjordFlix og kontrollér dens FjordHub-forbindelse.')
        try:
            data=json.loads(result.output)
            if not isinstance(data,dict) or data.get('ok') is not True:raise ValueError()
            return data
        except (ValueError,TypeError):
            raise ValueError('FjordFlix returnerede et ukendt biblioteksformat.') from None

    def candidates(self):
        container=self.flix()
        sources=self.request(container).get('sources',[])
        if not isinstance(sources,list):raise ValueError('FjordFlix returnerede et ukendt biblioteksformat.')
        mounts=[m for m in container.attrs.get('Mounts',[]) if m.get('Type')=='bind'
                and safe_path(m.get('Source')) and safe_path(m.get('Destination'))]
        current=Storage(self.runtime).public()['path']
        paths=[r['path'] for r in sources[:100] if isinstance(r,dict) and r.get('available') is True and safe_path(r.get('path'))]
        choices=[]
        for path in dict.fromkeys(paths):
            relevant=sorted([m for m in mounts if PurePosixPath(path).is_relative_to(m['Destination'])],
                            key=lambda m:len(m['Destination']),reverse=True)
            if not relevant:continue
            mount=relevant[0]
            host=str(PurePosixPath(mount['Source'])/PurePosixPath(path).relative_to(mount['Destination']))
            if not safe_path(host) or host in ('/mnt','/media','/srv'):continue
            key=hashlib.sha256((host+'\0'+path).encode()).hexdigest()[:32]
            choices.append({'id':key,'path':host,'library_path':path,'current':host==current})
        return {'available':True,'choices':choices}

    def connect(self,ident):
        if not isinstance(ident,str):raise ValueError('Vælg en fælles biblioteksmappe.')
        choices=self.candidates()['choices']
        selected=next((p for p in choices if p['id']==ident),None)
        if selected is None:raise ValueError('Vælg en tilgængelig FjordFlix-mappe.')
        storage=Storage(self.runtime)
        # Validate before changing Seed's mounts. Flix keeps its existing sources.
        storage.helper('browse',selected['path'])
        if not storage.helper('mount',selected['path'])['ready']:
            raise ValueError('Lageret skal først monteres på serveren.')
        storage.helper('writable',source=selected['path'])
        storage.select(selected['path'])
        return self.save(True,{'host_path':selected['path'],'library_path':selected['library_path']})
