"""Scoped device tokens and a Docker-isolated transfer broker for PC conversion."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
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
OWNER = 'dk.fjordseed.remote-owner'


class BrokerBusy(ValueError):pass


class RemoteConversion:
    def __init__(self, state, runtime):
        self.state, self.runtime = state, runtime
        self.path = state.root / 'conversion-devices.json'
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
        now=time.time()
        return [{k:d.get(k) for k in ('id','name','created_at','last_seen')} |
                {'online':0<=now-d.get('last_seen',0)<45} for d in devices]

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
                    d['last_seen']=time.time();self.write(devices);return
        raise ValueError('Pc-forbindelsen er fjernet.')

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

    @worker.post('/claim')
    def claim():
        return jsonify(job=invoke('claim'))

    @worker.get('/jobs/<ident>/files/<int:index>')
    def download(ident,index):
        offset=request.args.get('offset','0')
        if not offset.isdecimal() or len(offset)>16:raise ValueError('Ugyldigt filinterval.')
        data=invoke('read',{'job':ident,'lease':request.headers.get('X-Job-Lease',''),
                            'index':index,'offset':int(offset),'size':CHUNK},raw=True)
        from flask import Response
        return Response(data,mimetype='application/octet-stream',headers={'X-Chunk-SHA256':hashlib.sha256(data).hexdigest()})

    @worker.put('/jobs/<ident>/files/<int:index>')
    def upload(ident,index):
        request.max_content_length=CHUNK
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
                    conversion_bitrate=data.get('conversion_bitrate'),conversion_target=target)
            return jsonify(**result,devices=manager.public())
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.post('/api/conversion/devices')
    def create_device():
        try:return jsonify(manager.create(body().get('name'))),201
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.post('/api/conversion/devices/<ident>/revoke')
    def revoke_device(ident):
        try:manager.revoke(ident);return jsonify(ok=True)
        except ValueError as exc:return jsonify(error=str(exc)),400
