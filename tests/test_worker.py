import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from qbit_worker import configure, ready
import qbit_rpc
import qbit_worker


@pytest.fixture
def vpn(tmp_path):
    (tmp_path/'status.json').write_text(json.dumps({'healthy':True,'checked_at':100,'public_ip':'203.0.113.5', 'relay_enabled':False,'public_port':45000}))
    return tmp_path


def test_health_interface_freshness_relay_and_port_gate(vpn):
    assert ready(vpn,105,['lo','tun0']) == (45000,'203.0.113.5','')
    for now,interfaces in [(120,['tun0']),(90,['tun0']),(105,['eth0'])]:
        with pytest.raises(ValueError):ready(vpn,now,interfaces)
    status=json.loads((vpn/'status.json').read_text())
    status['relay_enabled']=True
    (vpn/'status.json').write_text(json.dumps(status))
    with pytest.raises(ValueError):ready(vpn,105,['tun0'])
    status['relay_enabled']=False
    for port in ('0','65536','8080','bad'):
        status['public_port']=port
        (vpn/'status.json').write_text(json.dumps(status))
        with pytest.raises(ValueError):ready(vpn,105,['tun0'])


def test_config_binds_before_launch_and_preserves_other_settings(tmp_path):
    configure(40001,tmp_path)
    path=tmp_path/'qBittorrent/config/qBittorrent.conf'
    assert 'Session\\Interface=tun0' in path.read_text()
    assert 'WebUI\\Address=127.0.0.1' in path.read_text()
    assert 'Session\\QueueingSystemEnabled=true' in path.read_text()
    assert 'Session\\MaxActiveDownloads=8' in path.read_text()
    assert 'Session\\MaxActiveUploads=-1' in path.read_text()
    assert 'Session\\MaxActiveTorrents=-1' in path.read_text()
    assert 'Session\\IgnoreSlowTorrentsForQueueing=false' in path.read_text()
    assert 'PortForwardingEnabled=false' in path.read_text()
    with path.open('a') as f:f.write('\n[Custom]\nKeep=1\n')
    configure(40002,tmp_path)
    assert 'Keep=1' in path.read_text() and 'Session\\Port=40002' in path.read_text()


def test_rpc_refuses_unbound_client_and_preserves_files_by_default(monkeypatch):
    fake=Mock(return_value=Mock(json=lambda:{'current_network_interface':'','upnp':False}))
    monkeypatch.setattr(qbit_rpc,'call',fake)
    with pytest.raises(RuntimeError):qbit_rpc.execute('add',{'magnet':'magnet:?x'})
    assert fake.call_count==1
    fake.side_effect=lambda path,data=None:Mock(json=lambda:
        {'current_network_interface':'tun0','upnp':False} if path=='app/preferences' else
        [{'hash':'a'*40,'ratio':1,'seeding_time':0}])
    qbit_rpc.execute('delete',{'hash':'a'*40})
    assert fake.call_args.args==('torrents/delete',{'hashes':'a'*40,'deleteFiles':'false'})


def test_supervisor_terminates_running_client_when_vpn_fails(monkeypatch,caplog):
    stop=Mock()
    stop.is_set.side_effect=[False,False,True]
    monkeypatch.setattr(qbit_worker,'STOP',stop)
    monkeypatch.setattr(qbit_worker.signal,'signal',Mock())
    monkeypatch.setattr(qbit_worker,'ready',Mock(side_effect=[(40001,'203.0.113.1','France'),ValueError('VPN lost')]))
    monkeypatch.setattr(qbit_worker,'configure',Mock())
    monkeypatch.setattr(qbit_worker,'sync_download_queue',Mock())
    monkeypatch.setattr(qbit_worker,'atomic',Mock())
    monkeypatch.setattr(qbit_worker,'call',Mock(return_value=Mock(json=lambda:{'current_network_interface':'tun0','upnp':False,'listen_port':40001})))
    session=Mock()
    session.__enter__=Mock(return_value=session);session.__exit__=Mock(return_value=False)
    session.get.return_value.status_code=200
    monkeypatch.setattr('requests.Session',Mock(return_value=session))
    process=Mock();process.poll.return_value=None
    monkeypatch.setattr(qbit_worker.subprocess,'Popen',Mock(return_value=process))
    qbit_worker.run()
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(10)
    assert qbit_worker.atomic.call_args_list[-1].args[1].find('false')>=0
    failure=json.loads(qbit_worker.atomic.call_args_list[1].args[1])['last_failure']
    assert failure['stage']=='vpn_status' and failure['error_type']=='ValueError'
    assert 'qBittorrent safety stop' in caplog.text
    assert 'VPN lost' not in caplog.text


def test_policy_failure_keeps_healthy_seeders_running(monkeypatch):
    stop=Mock()
    stop.is_set.side_effect=[False,True]
    monkeypatch.setattr(qbit_worker,'STOP',stop)
    monkeypatch.setattr(qbit_worker.signal,'signal',Mock())
    monkeypatch.setattr(qbit_worker,'ready',Mock(return_value=(40001,'203.0.113.1','France')))
    monkeypatch.setattr(qbit_worker,'configure',Mock())
    monkeypatch.setattr(qbit_worker,'sync_download_queue',Mock())
    monkeypatch.setattr(qbit_worker,'sync_share_limits',Mock(side_effect=OSError('policy unavailable')))
    monkeypatch.setattr(qbit_worker,'atomic',Mock())
    monkeypatch.setattr(qbit_worker,'call',Mock(return_value=Mock(json=lambda:{'current_network_interface':'tun0','upnp':False,'listen_port':40001,'stop_tracker_timeout':2})))
    session=Mock()
    session.__enter__=Mock(return_value=session);session.__exit__=Mock(return_value=False)
    session.get.return_value.status_code=200
    monkeypatch.setattr('requests.Session',Mock(return_value=session))
    process=Mock();process.poll.return_value=None
    monkeypatch.setattr(qbit_worker.subprocess,'Popen',Mock(return_value=process))
    stop.wait.side_effect=lambda _:process.terminate.assert_not_called()
    qbit_worker.run()
    status=json.loads(qbit_worker.atomic.call_args_list[0].args[1])
    assert status['ready'] and status['seeding_error']
    # Normal supervisor shutdown still stops the process.
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(30)
    assert any(call.args==('app/setPreferences',{'json':json.dumps({'stop_tracker_timeout':10})})
               for call in qbit_worker.call.call_args_list)


def test_failure_diagnostics_survive_recovery_without_private_error_text(monkeypatch,caplog):
    stop=Mock();stop.is_set.side_effect=[False,False,True]
    monkeypatch.setattr(qbit_worker,'STOP',stop)
    monkeypatch.setattr(qbit_worker.signal,'signal',Mock())
    monkeypatch.setattr(qbit_worker,'vpn_status',Mock(side_effect=[None,{}]))
    monkeypatch.setattr(qbit_worker,'ready',Mock(side_effect=[
        ValueError('https://private.example/?passkey=secret'),(40001,'203.0.113.1','France')]))
    monkeypatch.setattr(qbit_worker,'configure',Mock())
    monkeypatch.setattr(qbit_worker,'sync_download_queue',Mock())
    monkeypatch.setattr(qbit_worker,'sync_share_limits',Mock(return_value=[]))
    monkeypatch.setattr(qbit_worker,'atomic',Mock())
    monkeypatch.setattr(qbit_worker,'call',Mock(return_value=Mock(json=lambda:{
        'current_network_interface':'tun0','upnp':False,'listen_port':40001})))
    session=Mock();session.__enter__=Mock(return_value=session);session.__exit__=Mock(return_value=False)
    session.get.return_value.status_code=200
    monkeypatch.setattr('requests.Session',Mock(return_value=session))
    process=Mock();process.poll.return_value=None
    monkeypatch.setattr(qbit_worker.subprocess,'Popen',Mock(return_value=process))
    qbit_worker.run()
    failed,recovered=[json.loads(c.args[1]) for c in qbit_worker.atomic.call_args_list[:2]]
    assert not failed['ready'] and recovered['ready']
    assert recovered['last_failure']==failed['last_failure']
    assert recovered['last_failure']['stage']=='vpn_status'
    assert 'secret' not in caplog.text and 'private.example' not in caplog.text


def test_graceful_stop_waits_for_stopped_announces_before_killing():
    process=Mock();process.poll.return_value=None
    qbit_worker.stop_process(process,graceful=True)
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(30)
    process.kill.assert_not_called()


def test_unresponsive_shutdown_is_bounded():
    process=Mock();process.poll.return_value=None
    process.wait.side_effect=[qbit_worker.subprocess.TimeoutExpired('qbit',30),0]
    qbit_worker.stop_process(process,graceful=True)
    process.kill.assert_called_once()
    assert [call.args[0] for call in process.wait.call_args_list]==[30,3]
