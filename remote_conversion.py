"""Scoped device tokens and a Docker-isolated transfer broker for PC conversion."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import secrets
import tarfile
import threading
import time
import uuid

import docker
from flask import Blueprint, jsonify, request

from state import atomic
from storage import Storage
from streaming import Streaming

CHUNK = 8 * 1024 * 1024
DOWNLOAD_CHUNK = 32 * 1024 * 1024
UPLOAD_CHUNK = 32 * 1024 * 1024
OWNER = 'dk.fjordseed.remote-owner'


class BrokerBusy(ValueError):pass


def series(name):
    parts=PurePosixPath(name).parts
    for index,part in enumerate(parts):
        match=re.search(r'(?i)(?<![a-z0-9])(?:s\d{1,2}(?:e\d{1,3})?|season[ ._-]*\d+|sæson[ ._-]*\d+|\d{1,2}x\d{1,3})(?=[ ._-]|$)',part)
        if not match:continue
        title=part[:match.start()].strip(' ._-') or (parts[index-1] if index else '')
        title=re.sub(r'[._]+',' ',title).strip()
        key=re.sub(r'\s+',' ',title).lower()
        if key:return {'series_key':key,'series_name':title}
    return {}


def skipped(name,rules,series_key=None):
    name=name.lower()
    family=series_key or series(name).get('series_key')
    matches=[r for r in rules if (family==r['path'] if r['kind']=='series' else
        name==r['path'].lower() if r['kind']=='file' else not r['path'] or name.startswith(r['path'].lower()+'/'))]
    return matches[-1]['skip'] if matches else False


class RemoteConversion:
    def __init__(self, state, runtime):
        self.state, self.runtime = state, runtime
        self.path = state.root / 'conversion-devices.json'
        self.rules_path = state.root / 'conversion-skips.json'
        self.helper_lock = threading.Lock()
        self.verify_slots = threading.BoundedSemaphore(2)

    def devices(self):
        if not self.path.exists():return []
        return json.loads(self.path.read_text(encoding='utf-8'))

    def write(self, devices):
        atomic(self.path,json.dumps(devices),mode=0o600)

    def public(self):
        with self.state.lock:
            devices=self.devices()
            rules=self.rules()
        now=time.time()
        return [{k:d.get(k) for k in ('id','name','created_at','last_seen','media_folder','files','files_updated_at','files_truncated','selection','conversion_version')} |
                {'online':0<=now-d.get('last_seen',0)<45,
                 'queue':[q for q in d.get('queue',[]) if q['state'] in ('queued','running')],
                 'server_fallback_ready':getattr(self,'server_ready',False),
                 'files':[{**f,**series(f['name'])} for f in d.get('files',[])],
                 'skip_rules':rules.get(d['id'],{}).get(str(PureWindowsPath(d.get('media_folder') or '')).lower(),[]),
                 'gpu_ready':0<=now-d.get('gpu_ready_at',0)<45} for d in devices]

    def rules(self):
        return json.loads(self.rules_path.read_text(encoding='utf-8')) if self.rules_path.exists() else {}

    def skip(self,ident,folder,path,kind,value):
        if (kind not in ('file','folder','series') or type(value) is not bool or not isinstance(path,str) or len(path)>2048 or
                (not path and kind!='folder') or '\\' in path or ':' in path or any(ord(c)<32 for c in path) or
                (path and (PurePosixPath(path).is_absolute() or str(PurePosixPath(path))!=path or
                           any(p.startswith('.') for p in PurePosixPath(path).parts)))):
            raise ValueError('Vælg en fil eller mappe fra oversigten.')
        with self.state.lock:
            device=next((d for d in self.devices() if d['id']==ident),None)
            if not device or not folder or folder!=device.get('media_folder'):raise ValueError('Mappevalget er ændret. Opdatér oversigten.')
            rules=self.rules();key=str(PureWindowsPath(folder)).lower()
            current=rules.get(ident,{}).get(key,[])
            def matches(name):return series(name).get('series_key')==path if kind=='series' else name==path if kind=='file' else not path or name.startswith(path+'/')
            if value and not any(matches(f['name']) for f in device.get('files',[])):
                raise ValueError('Filen eller mappen findes ikke i oversigten.')
            selected=device.get('selection',{})
            if value and selected.get('action')=='convert' and selected.get('state') not in ('completed','error','cancelled') and matches(selected.get('name','')):
                raise ValueError('Afvent eller afbryd den igangværende konvertering før den springes over.')
            # A whole-folder action also resets rules below that folder.
            keep=[r for r in current if not (r['path'].lower()==path.lower() and r['kind']==kind) and
                  not (kind=='folder' and (not path or r['path'].lower().startswith(path.lower()+'/')))]
            if kind=='series':
                keep=[r for r in keep if not (r['path'] and r['kind']!='series' and
                    (series(r['path']).get('series_key')==path or
                     (r['kind']=='folder' and any(f['name'].startswith(r['path']+'/') for f in device.get('files',[])) and
                      all(series(f['name']).get('series_key')==path for f in device.get('files',[]) if f['name'].startswith(r['path']+'/')))))]
            sample=next((f['name'] for f in device.get('files',[]) if matches(f['name'])),path)
            families={series(f['name']).get('series_key') for f in device.get('files',[]) if matches(f['name'])}
            family=next(iter(families)) if len(families)==1 else None
            if value or skipped(sample if kind=='series' else path+'/file' if kind=='folder' else path,keep,family):
                keep.append({'path':path,'kind':kind,'skip':value})
            rules.setdefault(ident,{})[key]=keep
            if sum(len(rows) for scopes in rules.values() for rows in scopes.values())>10000:raise ValueError('For mange regler for filer og mapper.')
            atomic(self.rules_path,json.dumps(rules),mode=0o600)
            return {'ok':True,'media_folder':folder,'skip_rules':keep}

    def bitrates(self,ident):
        with self.state.lock:
            device=next((d for d in self.devices() if d['id']==ident),None)
            if not device:raise ValueError('Pc-forbindelsen findes ikke.')
            folder=device.get('media_folder','')
            files=device.get('files',[])
        if not folder:return {'media_folder':'','files':[],'pending':False}
        return {'media_folder':folder,**self.runtime.rpc('library-bitrates',{'files':files})}

    def create(self, name):
        if not isinstance(name,str) or not 1<=len(name.strip())<=60 or any(ord(c)<32 for c in name):
            raise ValueError('Giv pc’en et navn på højst 60 tegn.')
        token='fsw_'+secrets.token_urlsafe(36)
        device={'id':uuid.uuid4().hex,'name':name.strip(),'digest':hashlib.sha256(token.encode()).hexdigest(),
                'created_at':time.time(),'last_seen':0}
        with self.state.lock:
            devices=self.devices()
            if len(devices)>=20:raise ValueError('Fjern en eksisterende pc-forbindelse først.')
            devices.append(device);self.write(devices)
        return {'id':device['id'],'name':device['name'],'token':token}

    def revoke(self, ident):
        with self.state.lock:
            devices=self.devices()
            if not any(d['id']==ident for d in devices):raise ValueError('Pc-forbindelsen findes ikke.')
            self.write([d for d in devices if d['id']!=ident])
            if self.rules_path.exists():
                rules=self.rules();rules.pop(ident,None)
                atomic(self.rules_path,json.dumps(rules),mode=0o600)

    def authenticate(self, header):
        if not isinstance(header,str) or not header.startswith('Bearer fsw_') or len(header)>150:return None
        digest=hashlib.sha256(header[7:].encode()).hexdigest()
        with self.state.lock:
            return next((d for d in self.devices() if secrets.compare_digest(digest,d['digest'])),None)

    def touch(self, device):
        with self.state.lock:
            devices=self.devices()
            for d in devices:
                if d['id']==device['id']:
                    d['last_seen']=time.time();d['gpu_ready_at']=d['last_seen'];self.write(devices);return
        raise ValueError('Pc-forbindelsen er fjernet.')

    def select_file(self, ident, folder, name, bitrate=None):
        with self.state.lock:
            devices=self.devices()
            d=next((d for d in devices if d['id']==ident),None)
            if d is None:raise ValueError('Pc-forbindelsen findes ikke.')
            if not folder or folder!=d.get('media_folder'):
                raise ValueError('Mappevalget er ændret. Opdatér filoversigten.')
            entry=next((f for f in d.get('files',[]) if f['name']==name),None)
            if entry is None:raise ValueError('Filen findes ikke i pc’ens filoversigt.')
            rules=self.rules().get(ident,{}).get(str(PureWindowsPath(folder)).lower(),[])
            if skipped(name,rules):raise ValueError('Filen er sprunget over. Medtag den igen før konvertering.')
            if d.get('conversion_version')!=1:raise ValueError('Opdatér pc-programmet for at konvertere direkte fra netværksmappen.')
            bitrate=bitrate if bitrate is not None else self.state.get().get('streaming',{}).get('conversion_bitrate',30)
            if type(bitrate) is not int or bitrate not in (20,30,40):raise ValueError('Vælg 20, 30 eller 40 Mbps.')
            waiting=d.setdefault('queue',[])
            previous=d.get('selection') or {}
            if previous.get('state') in ('completed','cancelled','error'):
                for task in waiting:
                    if task.get('job_id')==previous.get('id') and task['state']=='running':task['state']=previous['state']
            if any(q['media_folder']==folder and q['name']==name and q['state'] in ('queued','running') for q in waiting):
                raise ValueError('Filen er allerede i konverteringskøen.')
            previous=d.get('selection') or {}
            if previous.get('name')==name and previous.get('media_folder')==folder and previous.get('state') not in ('completed','error','cancelled',None):
                raise ValueError('Filen er allerede under konvertering.')
            if sum(q['state'] in ('queued','running') for q in waiting)>=500:
                raise ValueError('Køen kan højst indeholde 500 filer.')
            task={'id':uuid.uuid4().hex,'media_folder':folder,'name':name,'size':entry['size'],
                  'bitrate':bitrate,'dolby_vision_mode':self.state.get().get('streaming',{}).get('conversion_dolby_vision','separate'),'state':'queued','created_at':time.time()}
            waiting.append(task)
            d['queue']=[q for q in waiting if q['state'] in ('queued','running')]+[q for q in waiting if q['state'] not in ('queued','running')][-20:]
            self.write(devices)  # Persist the request before any external work starts.
            if 0<=time.time()-d.get('last_seen',0)<45:self.start_next(d,'pc')
            self.write(devices)
            return d['selection'] if task.get('job_id') else task

    def start_next(self, device, executor):
        """Called under state.lock: only one selected job per PC, on either GPU."""
        selected=device.get('selection') or {}
        if selected.get('action')=='convert' and selected.get('state') not in ('completed','cancelled','error'):
            return
        for task in device.get('queue',[]):
            if task['state']=='running' and task.get('job_id')==selected.get('id'):
                task['state']=selected['state']
        task=next((q for q in device.get('queue',[]) if q['state']=='queued'),None)
        if not task:return
        if task['media_folder']!=device.get('media_folder'):
            task.update(state='cancelled',detail='Pc’ens mappe er ændret.');return
        try:
            selection=self.runtime.rpc('library-shared-queue',{'device':device['id'],
                **{k:task[k] for k in ('media_folder','name','size','bitrate')},
                'dolby_vision_mode':task.get('dolby_vision_mode','separate'),'executor':executor})
        except ValueError as exc:
            task['detail']=str(exc);return
        task.update(state='running',job_id=selection['id'],executor=executor);task.pop('detail',None)
        device['selection']={**selection,'queue_id':task['id'],'executor':executor}

    def cancel_queued(self, ident, task_id):
        with self.state.lock:
            devices=self.devices()
            device=next((d for d in devices if d['id']==ident),None)
            task=next((q for q in (device or {}).get('queue',[]) if q['id']==task_id),None)
            if not task or task['state']!='queued':raise ValueError('Kun ventende jobs kan fjernes fra køen.')
            task['state']='cancelled';self.write(devices)

    def tick(self):
        """Refresh durable job results and dispatch waiting work, including offline PCs."""
        with self.state.lock:
            devices=self.devices()
            if not any(q['state'] in ('queued','running') for d in devices for q in d.get('queue',[])):return
            self.server_ready=bool(os.environ.get('FJORDSEED_CONVERTER_CONTAINER') and
                self.runtime.rpc('library-shared-capacity',{}).get('ready') is True)
            for device in devices:
                online=0<=time.time()-device.get('last_seen',0)<45
                selected=device.get('selection') or {}
                if selected.get('action')=='convert' and selected.get('state') not in ('completed','cancelled','error'):
                    latest=self.runtime.rpc('library-shared-status',{'device':device['id'],'id':selected['id']})
                    if (not online and self.server_ready and latest.get('executor','pc')=='pc'
                            and not latest.get('claimed') and latest.get('state')=='queued'):
                        latest=self.runtime.rpc('library-shared-fallback',{'device':device['id'],'id':selected['id']})
                    if latest.get('executor')=='server' and latest.get('state')=='encoded':
                        latest=self.runtime.rpc('library-shared-complete',{'device':device['id'],'id':selected['id']})
                    device['selection']={**latest,'queue_id':selected.get('queue_id')}
                online=0<=time.time()-device.get('last_seen',0)<45
                if online or self.server_ready:self.start_next(device,'pc' if online else 'server')
            self.write(devices)

    def workspace(self, device, folder, files=None, truncated=False, receipt=None, conversion_version=0):
        # This is a PC-local path, never a server filesystem/mount instruction.
        if (not isinstance(folder,str) or len(folder)>2048 or
                any(ord(c)<32 for c in folder) or
                (folder and (not PureWindowsPath(folder).is_absolute() or
                             '..' in PureWindowsPath(folder).parts or
                             any(c in folder for c in '*?"<>|')))):
            raise ValueError('Send en absolut Windows-mappesti.')
        if files is not None:
            if not isinstance(files,list) or len(files)>5000 or type(truncated) is not bool:
                raise ValueError('Ugyldig filoversigt.')
            clean=[];seen=set()
            for entry in files:
                if not isinstance(entry,dict):raise ValueError('Ugyldig filoversigt.')
                name=entry.get('name');size=entry.get('size')
                if (not isinstance(name,str) or not 1<=len(name)<=2048 or '\\' in name or
                        any(ord(c)<32 for c in name) or PurePosixPath(name).is_absolute() or
                        any(p in ('..','.') or p.startswith('.') or ':' in p for p in name.split('/')) or
                        str(PurePosixPath(name))!=name or type(size) is not int or not 0<=size<2**63 or name in seen):
                    raise ValueError('Ugyldig filoversigt.')
                item={'name':name,'size':size}
                if entry.get('converted') is True and type(entry.get('bitrate')) is int and entry['bitrate'] in (20,30,40):
                    item.update(converted=True,bitrate=entry['bitrate'])
                clean.append(item);seen.add(name)
            if not folder and clean:raise ValueError('Vælg en mappe før filoversigten sendes.')
        if receipt is not None and (not isinstance(receipt,dict) or
                not isinstance(receipt.get('id'),str) or len(receipt['id'])!=32 or
                receipt.get('state') not in ('selected','converting','error') or
                (type(receipt.get('progress',0)) not in (int,float) or not 0<=receipt.get('progress',0)<=100) or
                not isinstance(receipt.get('detail',''),str) or len(receipt.get('detail',''))>300):
            raise ValueError('Ugyldig kvittering for filvalg.')
        with self.state.lock:
            devices=self.devices()
            for d in devices:
                if d['id']==device['id']:
                    if d.get('media_folder')!=folder:
                        for task in d.get('queue',[]):
                            if task['state']=='queued':task.update(state='cancelled',detail='Pc’ens mappe er ændret.')
                        old=d.get('selection',{})
                        if old.get('action')=='convert' and old.get('state') in ('queued','converting','encoding','error'):
                            self.runtime.rpc('library-shared-cancel',{'id':old['id'],'device':d['id']})
                        for key in ('files','files_updated_at','files_truncated'):d.pop(key,None)
                        if d.get('selection'):
                            d['selection'].update(state='cancelled',detail='Mappen er ændret i pc-programmet.')
                    if conversion_version not in (0,1):raise ValueError('Ukendt konverteringsversion.')
                    d.update(media_folder=folder,last_seen=time.time(),conversion_version=conversion_version)
                    if files is not None:
                        d.update(files=clean,files_updated_at=time.time(),files_truncated=truncated)
                    selection=d.get('selection')
                    if selection and selection.get('executor')!='server' and selection['state'] in ('queued','selected','converting'):
                        if files is not None and not any(f['name']==selection['name'] and f['size']==selection['size'] for f in clean):
                            selection.update(state='error',detail='Filen er ændret eller findes ikke længere i den valgte mappe.')
                        elif receipt and receipt['id']==selection['id']:
                            selection.update(state=receipt['state'],detail=receipt.get('detail',''),progress=receipt.get('progress',0))
                            stage=receipt.get('stage')
                            if stage in ('probing','encoding','metadata','verifying','server_verifying'):
                                if selection.get('stage')!=stage:selection['stage_started_at']=time.time()
                                selection.update(stage=stage,at=time.time())
                                value=receipt.get('phase_progress')
                                selection['phase_progress']=value if type(value) in (int,float) and 0<=value<=100 else None
                            elif receipt['state']=='converting':selection['stage']='encoding'
                        if selection.get('action')=='convert' and selection['state']=='error':
                            self.runtime.rpc('library-shared-error',{'id':selection['id'],'device':d['id'],'detail':selection.get('detail','')})
                    if selection and selection.get('action')=='convert' and selection['state']=='error':
                        latest=self.runtime.rpc('library-shared-status',{'id':selection['id'],'device':d['id']})
                        if isinstance(latest,dict) and (latest.get('attempt')!=selection.get('attempt') or latest.get('phase') in ('cancelled','published')):
                            selection=d['selection']=latest
                    self.start_next(d,'pc')
                    selection=d.get('selection')
                    self.write(devices)
                    return {'ok':True,'media_folder':folder,'selection':None if selection and selection.get('executor')=='server' else selection}
        raise ValueError('Pc-forbindelsen er fjernet.')

    def shared_result(self, device, ident, complete=False, cancel=False):
        with self.state.lock:
            current=next((d for d in self.devices() if d['id']==device['id']),{})
            selected=current.get('selection') or {}
            if selected.get('id')==ident and selected.get('executor')=='server':
                raise ValueError('Jobbet behandles af serverens GPU.')
        if complete and not self.verify_slots.acquire(blocking=False):raise BrokerBusy('Resultatkontrollen er optaget. Prøv igen.')
        try:
            result=self.runtime.rpc('library-shared-'+('complete' if complete else 'cancel' if cancel else 'status'),{'device':device['id'],'id':ident,**({'claim':True} if not complete and not cancel else {})})
        finally:
            if complete:self.verify_slots.release()
        with self.state.lock:
            devices=self.devices()
            for d in devices:
                if d['id']==device['id'] and d.get('selection',{}).get('id')==ident:
                    d['selection']=result;self.write(devices);break
        return result

    def helper(self):
        r=self.runtime
        identity=self.state.get()['id']
        storage=Storage(r)
        roots=list(dict.fromkeys([r.host_downloads.as_posix(),*storage.mounts()]))
        signature=hashlib.sha256(json.dumps([r.image,roots,r.uid,r.gid]).encode()).hexdigest()
        name='fjordseed-'+identity+'-remote'
        with self.helper_lock:
            try:worker=r.client.containers.get(name)
            except docker.errors.NotFound:worker=None
            if worker and worker.labels.get(OWNER)!=identity:raise ValueError('Pc-brokeren tilhører en anden installation.')
            if worker and worker.labels.get('dk.fjordseed.remote-config')!=signature:
                worker.stop(timeout=5);worker.remove();worker=None
            if worker is None:
                for root in roots:storage.helper('writable',source=root)
                mounts=[docker.types.Mount('/buffers/'+str(i),str(PurePosixPath(root)/'.incomplete'),type='bind') for i,root in enumerate(roots)]
                mounts.append(docker.types.Mount('/rpc',str(r.host_data/'rpc'),type='bind',read_only=True))
                worker=r.client.containers.create(r.image,name=name,command=['sleep','infinity'],
                    network_disabled=True,read_only=True,user=f'{r.uid}:{r.gid}',mounts=mounts,
                    environment={'FJORDSEED_BUFFERS':':'.join('/buffers/'+str(i) for i in range(len(roots)))},
                    tmpfs={'/tmp':'rw,nosuid,noexec,size=64m'},cap_drop=['ALL'],security_opt=['no-new-privileges:true'],init=True,
                    labels={OWNER:identity,'dk.fjordseed.remote-config':signature,'com.docker.compose.project':r.project,
                            'com.docker.compose.service':'remote-conversion','com.docker.compose.oneoff':'True'},
                    mem_limit='1g',cpu_period=100000,cpu_quota=200000,restart_policy={'Name':'unless-stopped'},
                    log_config=docker.types.LogConfig(type='json-file',config={'max-size':'2m','max-file':'2'}))
            if worker.status!='running':worker.start()
            return worker

    def rpc(self, action, device, data=None, raw=False, worker=None):
        verification=action=='verify'
        if verification and not self.verify_slots.acquire(blocking=False):
            raise BrokerBusy('Serveren kontrollerer allerede to filer. Prøv igen om lidt.')
        try:return self._rpc(action,device,data,raw,worker)
        finally:
            if verification:self.verify_slots.release()

    def _rpc(self, action, device, data=None, raw=False, worker=None):
        worker=worker or self.helper()
        ident=uuid.uuid4().hex
        path=self.state.root/'rpc'/('remote-'+ident+'.json')
        atomic(path,json.dumps({**(data or {}),'worker':device['id'],'action':action}),mode=0o644)
        try:
            # A probe/statistics pass can exceed the ordinary Docker status timeout.
            client=docker.from_env(timeout=2400 if action=='verify' else 60)
            try:
                result=client.containers.get(worker.id).exec_run(['python','/app/remote_helper.py',ident])
            finally:
                client.close()
            if result.exit_code:
                failure={}
                try:
                    failure=json.loads(result.output)
                    message=failure['error']
                except (ValueError,KeyError):message='Pc-jobbet kunne ikke behandles.'
                if failure.get('busy'):raise BrokerBusy('Jobbet er optaget. Prøv igen om lidt.')
                raise ValueError(message)
            return result.output if raw else json.loads(result.output)['data']
        finally:
            path.unlink(missing_ok=True)

    def upload(self, device, data, payload):
        part=uuid.uuid4().hex
        data={**data,'part':part,'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
        worker=self.helper()
        target=self.rpc('prepare_upload',device,data,worker=worker)
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w') as archive:
            entry=tarfile.TarInfo(part);entry.size=len(payload);entry.mode=0o600
            entry.uid=self.runtime.uid;entry.gid=self.runtime.gid
            archive.addfile(entry,io.BytesIO(payload))
        stream.seek(0)
        if not worker.put_archive(target['directory'],stream):raise ValueError('Filblokken kunne ikke gemmes.')
        return self.rpc('append',device,data,worker=worker)


def register(app, state, runtime):
    manager=RemoteConversion(state,runtime)
    app.extensions['remote_conversion']=manager
    worker=Blueprint('conversion_worker',__name__,url_prefix='/api/conversion/worker')

    @worker.before_request
    def authenticate():
        from flask import g
        g.conversion_device=manager.authenticate(request.headers.get('Authorization',''))
        if not g.conversion_device:return jsonify(error='Ugyldigt eller fjernet pc-token.'),401

    def device():
        from flask import g
        return g.conversion_device

    def body():
        data=request.get_json(silent=True)
        if not isinstance(data,dict):raise ValueError('Send et JSON-objekt.')
        return data

    def invoke(action, data=None, raw=False):
        return manager.rpc(action,device(),data,raw=raw)

    @worker.errorhandler(ValueError)
    def bad_request(exc):return jsonify(error=str(exc)),423 if isinstance(exc,BrokerBusy) else 409

    @worker.errorhandler(docker.errors.DockerException)
    def docker_error(exc):return jsonify(error='Pc-brokeren er ikke klar. Kontrollér FjordSeed-installationen.'),503

    @worker.post('/heartbeat')
    def heartbeat():
        data=body()
        if data.get('version')!=1 or data.get('gpu_ready') is not True:
            raise ValueError('Pc’ens GPU-test skal bestå først.')
        manager.touch(device())
        invoke('heartbeat')
        if data.get('job'):invoke('renew',data)
        return jsonify(ok=True)

    @worker.post('/workspace')
    def workspace():
        data=body()
        if data.get('version')!=1:raise ValueError('Ukendt programversion.')
        return jsonify(manager.workspace(device(),data.get('media_folder'),data.get('files'),data.get('truncated',False),data.get('selection_result'),data.get('conversion_version',0)))

    @worker.route('/shared/<ident>',methods=['GET','POST'])
    def shared_job(ident):
        action=body().get('action') if request.method=='POST' else 'status'
        if action not in ('status','complete','cancel'):raise ValueError('Ukendt jobhandling.')
        return jsonify(manager.shared_result(device(),ident,complete=action=='complete',cancel=action=='cancel'))

    @worker.post('/claim')
    def claim():
        return jsonify(job=invoke('claim'))

    @worker.get('/jobs/<ident>/files/<int:index>')
    def download(ident,index):
        offset=request.args.get('offset','0')
        if not offset.isdecimal() or len(offset)>16:raise ValueError('Ugyldigt filinterval.')
        size=request.args.get('size',str(CHUNK))
        if not size.isdecimal() or len(size)>9 or not 1<=int(size)<=DOWNLOAD_CHUNK:raise ValueError('Ugyldig blokstørrelse.')
        data=invoke('read',{'job':ident,'lease':request.headers.get('X-Job-Lease',''),
                            'index':index,'offset':int(offset),'size':int(size)},raw=True)
        from flask import Response
        return Response(data,mimetype='application/octet-stream',headers={'X-Chunk-SHA256':hashlib.sha256(data).hexdigest()})

    @worker.put('/jobs/<ident>/files/<int:index>')
    def upload(ident,index):
        request.max_content_length=UPLOAD_CHUNK
        offset=request.args.get('offset','0')
        if not offset.isdecimal() or len(offset)>16:raise ValueError('Ugyldigt filinterval.')
        payload=request.get_data()
        result=manager.upload(device(),{'job':ident,'lease':request.headers.get('X-Job-Lease',''),
                                       'index':index,'offset':int(offset)},payload)
        return jsonify(result)

    @worker.post('/jobs/<ident>/<action>')
    def job_action(ident,action):
        if action not in ('verify','complete','fail'):return jsonify(error='Ukendt handling.'),404
        data=body()
        return jsonify(invoke(action,{**data,'job':ident,'lease':request.headers.get('X-Job-Lease','')}))

    app.register_blueprint(worker)

    @app.get('/api/conversion')
    def conversion_settings():
        return jsonify(**Streaming(runtime).public(),devices=manager.public())

    @app.post('/api/conversion')
    def save_conversion_settings():
        try:
            data=body();target=data.get('conversion_target')
            if target not in ('server','pc'):raise ValueError('Vælg server eller pc.')
            with state.lock:
                enabled=state.get().get('streaming',{}).get('enabled',True)
                result=Streaming(runtime).save(enabled,conversion_enabled=data.get('conversion_enabled'),
                    conversion_bitrate=data.get('conversion_bitrate'),conversion_target=target,
                    conversion_dolby_vision=data.get('conversion_dolby_vision'))
            return jsonify(**result,devices=manager.public())
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.get('/api/conversion/dolby-vision')
    def dolby_vision_files():
        try:return jsonify(runtime.rpc('library-dolby-list',{}))
        except ValueError as exc:return jsonify(error=str(exc)),409

    @app.post('/api/conversion/dolby-vision/<ident>/restore')
    def restore_dolby_vision(ident):
        try:return jsonify(runtime.rpc('library-dolby-restore',{'id':ident})),202
        except ValueError as exc:return jsonify(error=str(exc)),409

    @app.get('/api/conversion/library')
    def library_files():
        try:return jsonify(runtime.rpc('library-list',{}))
        except ValueError as exc:return jsonify(error=str(exc)),409

    @app.post('/api/conversion/library')
    def convert_library_file():
        try:
            data=body()
            return jsonify(runtime.rpc('library-convert',{'id':data.get('id'),'bitrate':data.get('bitrate')})),202
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.post('/api/conversion/library/<ident>/retry')
    def retry_library_file(ident):
        try:return jsonify(runtime.rpc('library-retry',{'id':ident}))
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.post('/api/conversion/library/<ident>/cancel')
    def cancel_library_file(ident):
        try:return jsonify(runtime.rpc('library-cancel',{'id':ident}))
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.post('/api/conversion/devices')
    def create_device():
        try:return jsonify(manager.create(body().get('name'))),201
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.post('/api/conversion/devices/<ident>/revoke')
    def revoke_device(ident):
        try:manager.revoke(ident);return jsonify(ok=True)
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.post('/api/conversion/devices/<ident>/select')
    def select_workspace_file(ident):
        try:
            data=body()
            return jsonify(selection=manager.select_file(ident,data.get('media_folder'),data.get('name'),data.get('bitrate'))),202
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.post('/api/conversion/devices/<ident>/skip')
    def skip_workspace_file(ident):
        try:
            data=body()
            return jsonify(manager.skip(ident,data.get('media_folder'),data.get('path'),data.get('kind'),data.get('skip')))
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.post('/api/conversion/devices/<ident>/queue/<task_id>/cancel')
    def cancel_queued_conversion(ident,task_id):
        try:manager.cancel_queued(ident,task_id);return jsonify(ok=True)
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.get('/api/conversion/devices/<ident>/bitrates')
    def workspace_bitrates(ident):
        try:return jsonify(manager.bitrates(ident))
        except ValueError as exc:return jsonify(error=str(exc)),409
