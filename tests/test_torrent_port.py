import json,struct
from unittest.mock import Mock,patch

import pytest
import torrent_port
from torrent_port import Lease,internal_port,request
from qbit_worker import ready,configure
from test_runtime import runtime
import qbit_worker


def test_gateway_uses_its_own_open_port_without_disabling_vpn_gate(tmp_path):
    status={'healthy':True,'checked_at':100,'public_ip':'185.111.109.2','public_port':53289,
            'relay_enabled':True,'gateway_enabled':True,'torrent_internal_port':56789}
    (tmp_path/'status.json').write_text(json.dumps(status))
    assert ready(tmp_path,105,['tun0'])==(53289,'185.111.109.2','')
    for changes in [{'healthy':False},{'gateway_enabled':'true'},{'checked_at':80}]:
        with pytest.raises(ValueError):ready(tmp_path,105,['tun0'],status={**status,**changes})
    with pytest.raises(ValueError):ready(tmp_path,105,['eth0'],status=status)


def test_natpmp_request_is_explicit_second_mapping_only(monkeypatch):
    sock=Mock();sock.__enter__=Mock(return_value=sock);sock.__exit__=Mock(return_value=False)
    sock.recv.return_value=struct.pack('!BBHIHHI',0,129,0,100,56789,65279,60)
    monkeypatch.setattr(torrent_port.socket,'socket',Mock(return_value=sock))
    assert request('udp',56789)==65279
    sock.connect.assert_called_once_with(('10.2.0.1',5351))
    assert sock.send.call_args.args[0]==struct.pack('!BBHHHI',0,1,0,56789,0,60)
    for response in [b'bad',struct.pack('!BBHIHHI',0,129,2,100,56789,65279,60),
                     struct.pack('!BBHIHHI',0,129,0,100,0,65279,60)]:
        sock.recv.return_value=response
        with pytest.raises(ValueError):request('udp',56789)


def test_lease_renews_both_protocols_and_cleans_only_its_private_mapping(monkeypatch):
    call=Mock(return_value=65279);monkeypatch.setattr(torrent_port,'request',call)
    lease=Lease();assert lease.get(53289,0)==(56789,65279)
    assert call.call_args_list[0].args==('udp',56789,0)
    assert call.call_args_list[1].args==('tcp',56789,65279)
    assert lease.get(53290,10)==(56789,65279) and call.call_count==2
    assert lease.get(53290,21)==(56789,65279) and call.call_count==4
    lease.close()
    assert [x.args for x in call.call_args_list[-2:]]==[('udp',56789,65279,0),('tcp',56789,65279,0)]
    assert all(args.args[1]!=0 for args in call.call_args_list)


@pytest.mark.parametrize('values',[(65279,65280),(53289,53289),(56789,56789),(8080,8080)])
def test_conflicting_mapping_never_becomes_a_ready_torrent_port(monkeypatch,values):
    monkeypatch.setattr(torrent_port,'request',Mock(side_effect=values))
    lease=Lease()
    with pytest.raises(ValueError):lease.get(53289,0)
    assert not lease.public


def test_torrent_port_collision_and_failed_renewal_are_closed(monkeypatch):
    assert internal_port(56789)==56790
    call=Mock(return_value=65279);monkeypatch.setattr(torrent_port,'request',call)
    lease=Lease();lease.get(53289,0)
    call.side_effect=OSError('Provider unavailable')
    with pytest.raises(OSError):lease.get(53289,21)
    lease.close();assert not lease.public


@pytest.mark.parametrize('protocol',['udp','tcp'])
def test_renewal_timeout_reuses_only_confirmed_unexpired_lease(monkeypatch,protocol):
    call=Mock(return_value=65279);monkeypatch.setattr(torrent_port,'request',call)
    monkeypatch.setattr(torrent_port.time,'monotonic',lambda:0)
    lease=Lease();lease.get(53289,0)
    call.side_effect=[TimeoutError()] if protocol=='udp' else [65279,TimeoutError()]
    assert lease.get(53289,21)==(56789,65279)
    assert lease.expires==50 and lease.next_check==23
    count=call.call_count
    assert lease.get(53289,22)==(56789,65279) and call.call_count==count
    call.side_effect=None
    assert lease.get(53289,23)==(56789,65279)
    assert lease.expires==73 and call.call_count==count+2


def test_timeouts_never_extend_deadline_and_expiry_during_request_fails(monkeypatch):
    call=Mock(return_value=65279);monkeypatch.setattr(torrent_port,'request',call)
    monkeypatch.setattr(torrent_port.time,'monotonic',lambda:0)
    lease=Lease();lease.get(53289,0)
    call.side_effect=TimeoutError()
    for now in [21,26,31,36,41,46]:
        assert lease.get(53289,now)==(56789,65279)
        assert lease.expires==50
    monkeypatch.setattr(torrent_port.time,'monotonic',Mock(side_effect=[100,103]))
    with pytest.raises(TimeoutError):lease.get(53289,48)


def test_initial_partial_mapping_or_expired_lease_cannot_mask_timeout(monkeypatch):
    call=Mock(side_effect=[65279,TimeoutError()]);monkeypatch.setattr(torrent_port,'request',call)
    lease=Lease()
    with pytest.raises(TimeoutError):lease.get(53289,0)
    assert lease.public==0 and lease.expires==0
    call.side_effect=None;call.return_value=65279
    lease.get(53289,0)
    call.side_effect=TimeoutError()
    with pytest.raises(TimeoutError):lease.get(53289,50)


def test_conflicting_renewal_reply_is_not_treated_as_packet_loss(monkeypatch):
    call=Mock(return_value=65279);monkeypatch.setattr(torrent_port,'request',call)
    lease=Lease();lease.get(53289,0)
    call.side_effect=[65279,65280]
    with pytest.raises(ValueError):lease.get(53289,21)


def test_gateway_config_preserves_speed_settings_and_reports_the_external_port(tmp_path):
    configure(38850,tmp_path)
    path=tmp_path/'qBittorrent/config/qBittorrent.conf'
    content=path.read_text();content=content.replace('Session\\Port=38850','Session\\Port=38850\nSession\\GlobalDLSpeedLimit=123\nSession\\GlobalUPSpeedLimit=456')
    path.write_text(content)
    configure(56789,tmp_path,announce_port=65279)
    saved=path.read_text()
    assert 'Session\\Port=56789' in saved and 'Session\\AnnouncePort=65279' in saved
    assert 'Session\\Interface=tun0' in saved and 'PortForwardingEnabled=false' in saved
    assert 'Session\\GlobalDLSpeedLimit=123' in saved and 'Session\\GlobalUPSpeedLimit=456' in saved


def test_gateway_selection_gets_native_port_rules_without_proxy_or_host_ports(runtime):
    profile=runtime.discover.return_value[1][0]
    profile.update(gateway_enabled=True,relay_enabled=True)
    profile['status']['public_port']=53289
    runtime.vpn.exec_run.side_effect=[Mock(exit_code=1),Mock(exit_code=0),Mock(exit_code=1),Mock(exit_code=0)]
    runtime.configure({'enabled':True,'profile_id':profile['id']})
    runtime.reconcile()
    commands=[x.args[0] for x in runtime.vpn.exec_run.call_args_list]
    assert all(command[0]=='iptables' for command in commands)
    assert all('tun0' in command and '56789' in command for command in commands)
    assert any('tcp' in command for command in commands) and any('udp' in command for command in commands)
    args=runtime.client.containers.create.call_args.kwargs
    assert args['network_mode']=='container:vpn-id' and 'ports' not in args
    assert args['labels']['dk.fjordseed.torrent-mode']=='gateway'
    status=json.loads((runtime.state.root/'vpn/status.json').read_text())
    assert status['gateway_enabled'] and status['torrent_internal_port']==56789
    assert status['relay_enabled']


def test_mapping_failure_stops_qbittorrent_and_reports_external_port(monkeypatch):
    stop=Mock();stop.is_set.side_effect=[False,False,True]
    monkeypatch.setattr(qbit_worker,'STOP',stop)
    monkeypatch.setattr(qbit_worker.signal,'signal',Mock())
    monkeypatch.setattr(qbit_worker,'vpn_status',Mock(return_value={'gateway_enabled':True,'torrent_internal_port':56789}))
    monkeypatch.setattr(qbit_worker,'ready',Mock(return_value=(53289,'185.111.109.2','DK')))
    lease=Mock();lease.get.side_effect=[(56789,65279),OSError('lease lost')]
    monkeypatch.setattr(qbit_worker,'Lease',Mock(return_value=lease))
    configure_mock=Mock();monkeypatch.setattr(qbit_worker,'configure',configure_mock)
    monkeypatch.setattr(qbit_worker,'sync_download_queue',Mock())
    monkeypatch.setattr(qbit_worker,'sync_share_limits',Mock(return_value=[]))
    writes=Mock();monkeypatch.setattr(qbit_worker,'atomic',writes)
    monkeypatch.setattr(qbit_worker,'call',Mock(return_value=Mock(json=lambda:{
        'current_network_interface':'tun0','upnp':False,'listen_port':56789,'announce_port':65279})))
    health=Mock();health.__enter__=Mock(return_value=health);health.__exit__=Mock(return_value=False)
    health.get.return_value.status_code=200
    monkeypatch.setattr('requests.Session',Mock(return_value=health))
    process=Mock();process.poll.return_value=None
    monkeypatch.setattr(qbit_worker.subprocess,'Popen',Mock(return_value=process))
    qbit_worker.run()
    process.terminate.assert_called_once();process.wait.assert_called_once_with(10)
    configure_mock.assert_called_once_with(56789,announce_port=65279)
    status=json.loads(writes.call_args_list[0].args[1])
    assert status['ready'] and status['port']==65279 and status['internal_port']==56789
    assert status['torrent_mode']=='gateway'
    assert not json.loads(writes.call_args_list[1].args[1])['ready']
    failure=json.loads(writes.call_args_list[1].args[1])['last_failure']
    assert failure['stage']=='torrent_port' and failure['error_type']=='OSError'
    assert lease.close.call_count>=2


def test_gateway_status_keeps_public_port_when_rpc_returns_internal_port(runtime):
    runtime.state.save('a'*32,True)
    runtime.child.return_value=Mock(status='running')
    runtime.rpc=Mock(return_value={'port':56789,'torrents':[]})
    import time
    (runtime.state.root/'qbit/worker-status.json').write_text(json.dumps({
        'ready':True,'checked_at':time.time(),'torrent_mode':'gateway',
        'public_torrent_port':65279,'internal_port':56789,'port':65279}))
    assert runtime.status()['port']==65279
    assert runtime.status()['torrents_available'] is True


def test_stopped_gateway_seedbox_removes_only_its_marked_firewall_rules(runtime):
    profile=runtime.discover.return_value[1][0];profile.update(gateway_enabled=True,relay_enabled=True)
    profile['status']['public_port']=53289
    runtime.vpn.exec_run.side_effect=[Mock(exit_code=x) for x in [1,0,1,0,0,0,0,0]]
    runtime.reconcile();ledger=runtime.state.root/'torrent-firewall.json'
    assert ledger.exists()
    runtime.stop();assert not ledger.exists()
    removals=[x.args[0] for x in runtime.vpn.exec_run.call_args_list if '-D' in x.args[0]]
    assert len(removals)==2 and all('56789' in r and '53289' not in r for r in removals)
    assert all('fjordseed-'+runtime.state.get()['id'] in r and 'tun0' in r for r in removals)


def test_firewall_cleanup_preserves_foreign_vpn_installation(runtime):
    import runtime as module
    profile=runtime.discover.return_value[1][0]
    ledger=runtime.state.root/'torrent-firewall.json'
    ledger.write_text(json.dumps({module.PROFILE:profile['id'],'dk.fjordseed.vpn-project':'foreign',
        'dk.fjordseed.torrent-internal-port':'56789'}))
    with pytest.raises(ValueError):runtime.stop()
    runtime.vpn.exec_run.assert_not_called()
    assert ledger.exists()
