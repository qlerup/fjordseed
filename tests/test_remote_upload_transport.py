import io
import tarfile
from types import SimpleNamespace
from unittest.mock import Mock

from remote_conversion import RemoteConversion


def test_uploaded_tar_chunk_is_owned_by_unprivileged_broker(tmp_path):
    worker=Mock()
    manager=RemoteConversion(SimpleNamespace(root=tmp_path),SimpleNamespace(uid=1234,gid=2345))
    manager.helper=Mock(return_value=worker)
    manager.rpc=Mock(side_effect=[{'directory':'/scoped/incoming'}, {'offset':4}])
    def receive(path,stream):
        assert path=='/scoped/incoming'
        with tarfile.open(fileobj=stream) as archive:
            item=archive.getmembers()[0]
            assert item.uid==1234 and item.gid==2345 and item.mode==0o600
            assert len(item.name)==32 and '/' not in item.name
            assert archive.extractfile(item).read()==b'data'
        return True
    worker.put_archive.side_effect=receive
    assert manager.upload({'id':'device'},{'index':0,'offset':0},b'data')=={'offset':4}


def test_docker_client_is_closed_after_broker_exec(tmp_path,monkeypatch):
    from state import State
    import remote_conversion
    state=State(tmp_path);(tmp_path/'rpc').mkdir()
    worker=Mock(id='helper')
    client=Mock();client.containers.get.return_value.exec_run.return_value=SimpleNamespace(exit_code=0,output=b'{"ok":true,"data":null}')
    monkeypatch.setattr(remote_conversion.docker,'from_env',Mock(return_value=client))
    manager=RemoteConversion(state,Mock());manager.helper=Mock(return_value=worker)
    assert manager.rpc('claim',{'id':'worker'}) is None
    client.close.assert_called_once()
    assert not list((tmp_path/'rpc').glob('remote-*.json'))
