"""Create the GPU queue from the toolchain service installed/tested by FjordHub."""
import hashlib
import json
import os
from pathlib import PurePosixPath

import docker
from storage import Storage

OWNER='dk.fjordseed.converter-owner'


def sync(runtime):
    name=os.environ.get('FJORDSEED_CONVERTER_CONTAINER','')
    if not name:return
    try:template=runtime.client.containers.get(name)
    except docker.errors.NotFound:raise ValueError('GPU-servicen er ikke installeret endnu.') from None
    if (template.labels.get('com.docker.compose.project')!=runtime.project or
            template.labels.get('com.docker.compose.service')!='converter'):
        raise ValueError('GPU-servicen tilhører ikke denne FjordSeed-installation.')
    identity=runtime.state.get()['id']
    worker_name='fjordseed-'+identity+'-converter'
    try:worker=runtime.client.containers.get(worker_name)
    except docker.errors.NotFound:worker=None
    if worker and worker.labels.get(OWNER)!=identity:raise ValueError('GPU-workeren tilhører en anden installation.')
    storage=Storage(runtime)
    roots=list(dict.fromkeys([runtime.host_downloads.as_posix(),*storage.mounts()]))
    gpu=template.attrs['HostConfig']
    devices=gpu.get('Devices') or []
    requests=gpu.get('DeviceRequests') or []
    if not requests:raise ValueError('GPU-servicen mangler NVIDIA Container Toolkit-adgang.')
    signature=hashlib.sha256(json.dumps(['shared-queue-v1',template.attrs['Image'],roots,runtime.uid,runtime.gid,devices,requests],sort_keys=True).encode()).hexdigest()
    if worker and worker.labels.get('dk.fjordseed.converter-config')!=signature:
        worker.stop(timeout=30);worker.remove();worker=None
    if worker is None:
        for root in roots:storage.helper('writable',source=root)
        mounts=[docker.types.Mount('/buffers/'+str(i),str(PurePosixPath(root)/'.incomplete'),type='bind') for i,root in enumerate(roots)]
        mounts.extend(docker.types.Mount('/shared/'+str(i),str(PurePosixPath(root)/'.fjordseed-shared'),type='bind') for i,root in enumerate(roots))
        worker=runtime.client.containers.create(template.attrs['Image'],name=worker_name,
            command=['python3','/app/converter_worker.py'],network_disabled=True,read_only=True,
            user=f'{runtime.uid}:{runtime.gid}',mounts=mounts,
            environment={'FJORDSEED_BUFFERS':':'.join([*('/buffers/'+str(i) for i in range(len(roots))),*('/shared/'+str(i) for i in range(len(roots)))]),
                         'NVIDIA_VISIBLE_DEVICES':'all','NVIDIA_DRIVER_CAPABILITIES':'compute,video,utility','LC_ALL':'C.UTF-8'},
            devices=[f"{d['PathOnHost']}:{d['PathInContainer']}:{d.get('CgroupPermissions','rwm')}" for d in devices],
            device_requests=[docker.types.DeviceRequest(driver=d.get('Driver',''),count=d.get('Count',-1),
                device_ids=d.get('DeviceIDs') or [],capabilities=d.get('Capabilities',[]),options=d.get('Options') or {}) for d in requests],
            tmpfs={'/tmp':'rw,nosuid,size=128m','/run/fjordseed-converter':f'rw,nosuid,uid={runtime.uid},gid={runtime.gid},mode=0700,size=1m'},
            cap_drop=['ALL'],security_opt=['no-new-privileges:true'],init=True,
            labels={OWNER:identity,'dk.fjordseed.converter-config':signature,
                    'com.docker.compose.project':runtime.project,'com.docker.compose.service':'conversion-worker',
                    'com.docker.compose.oneoff':'True'},
            mem_limit='6g',cpu_period=100000,cpu_quota=400000,
            restart_policy={'Name':'unless-stopped'},
            log_config=docker.types.LogConfig(type='json-file',config={'max-size':'5m','max-file':'2'}))
    if worker.status!='running':worker.start()
