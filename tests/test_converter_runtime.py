from pathlib import PurePosixPath
from unittest.mock import Mock
import docker
import pytest
from state import State
from converter_runtime import sync,OWNER


@pytest.fixture
def runtime(tmp_path,monkeypatch):
    monkeypatch.setenv('FJORDSEED_CONVERTER_CONTAINER','seed-converter')
    r=Mock();r.state=State(tmp_path);r.project='seed';r.uid=r.gid=1000
    r.host_downloads=PurePosixPath('/mnt/media');r.image='seed-app-image'
    template=Mock(labels={'com.docker.compose.project':'seed','com.docker.compose.service':'converter'},attrs={
        'Image':'converter-image','HostConfig':{'Devices':[{'PathOnHost':'/dev/nvidia0','PathInContainer':'/dev/nvidia0','CgroupPermissions':'rwm'}],
        'DeviceRequests':[{'Driver':'','Count':-1,'Capabilities':[['gpu']]}]}})
    r.client.containers.get.side_effect=[template,docker.errors.NotFound('missing')]
    monkeypatch.setattr('converter_runtime.Storage.helper',Mock(return_value={'writable':True}))
    return r


def test_worker_has_gpu_but_only_buffer_mounts_and_no_network(runtime):
    sync(runtime)
    args=runtime.client.containers.create.call_args.kwargs
    assert args['network_disabled'] and args['read_only'] and args['user']=='1000:1000'
    assert args['cap_drop']==['ALL'] and args['devices']==['/dev/nvidia0:/dev/nvidia0:rwm']
    assert len(args['mounts'])==1 and args['mounts'][0]['Source']=='/mnt/media/.incomplete'
    assert args['mounts'][0]['Target']=='/buffers/0'
    assert not any('docker.sock' in mount['Source'] for mount in args['mounts'])
    assert args['labels'][OWNER]==runtime.state.get()['id']


def test_uninstalled_gpu_has_no_effect_on_downloads(runtime,monkeypatch):
    monkeypatch.delenv('FJORDSEED_CONVERTER_CONTAINER')
    sync(runtime)
    runtime.client.containers.get.assert_not_called()
