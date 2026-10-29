import json
import time
from pathlib import Path, PurePosixPath
from unittest.mock import Mock

import pytest
from runtime import Runtime, GLUETUN, OWNER, PROFILE
from state import State


@pytest.mark.parametrize('failure',['missing_status','stale_status','worker_not_ready','rpc_failure','empty_success'])
def test_status_distinguishes_unavailable_torrents_from_confirmed_empty(runtime,failure):
    runtime.child.return_value=Mock(status='running')
    runtime.rpc=Mock(return_value={'torrents':[]})
    if failure!='missing_status':
        (runtime.state.root/'qbit/worker-status.json').write_text(json.dumps({
            'ready':failure!='worker_not_ready',
            'checked_at':time.time()-(20 if failure=='stale_status' else 0)}))
    if failure=='rpc_failure':runtime.rpc.side_effect=ValueError('unavailable')
    result=runtime.status()
    assert result['torrents']==[]
    assert result['torrents_available'] is (failure=='empty_success')
    assert result['ready'] is (failure=='empty_success')


@pytest.fixture
def runtime(tmp_path,monkeypatch):
    monkeypatch.setattr('runtime.Storage.ensure_seeder',Mock())
    r=Runtime.__new__(Runtime)
    r.state=State(tmp_path)
    (tmp_path/'vpn').mkdir()
    (tmp_path/'qbit').mkdir()
    r.state.save('a'*32, True)
    r.project='seed'; r.image='sha256:seed'; r.uid=r.gid=1000
    r.host_data=Path('/data/seed');r.host_downloads=Path('/downloads/seed')
    r.client=Mock();r.error='';r.profiles=[]
    manager=Mock(labels={'com.docker.compose.project':'vpn'})
    profile={'id':'a'*32,'desired':True,'relay_enabled':False,'status':{'healthy':False}}
    r.discover=Mock(return_value=(manager,[profile]))
    r.vpn=Mock(id='vpn-id',status='running', labels={'dk.fjordvpn.managed':'1', PROFILE:'a'*32,'com.docker.compose.project':'vpn'},
        attrs={'Config':{'Image':GLUETUN,'Env':['VPN_TYPE=wireguard','VPN_PORT_FORWARDING=on']},'State':{'StartedAt':'today'}})
    r.client.containers.get.return_value=r.vpn
    r.client.containers.list.return_value=[]
    r.child=Mock(return_value=None)
    return r


def test_child_has_only_vpn_network_and_no_keys_or_host_ports(runtime):
    runtime.reconcile()
    args=runtime.client.containers.create.call_args.kwargs
    assert args['network_mode']=='container:vpn-id'
    assert 'ports' not in args and 'devices' not in args
    assert args['user']=='1000:1000' and args['cap_drop']==['ALL']
    assert not any('wg0' in p or 'docker.sock' in p for p in (m['Source'] for m in args['mounts']))
    assert json.loads((runtime.state.root/'vpn/status.json').read_text())['healthy'] is False


@pytest.mark.parametrize('change', ['vpn_restart','image','storage','uid'])
def test_recreates_child_on_restart_upgrade_and_storage_change(runtime,change):
    child=Mock(status='running',labels={'dk.fjordseed.vpn-generation':'vpn-id:today'},attrs={
        'Image':runtime.image,'Config':{'User':'1000:1000'},'Mounts':[
            {'Type':'bind','Source':(runtime.host_data/'qbit').as_posix(),'Destination':'/config'},
            {'Type':'bind','Source':runtime.host_downloads.as_posix(),'Destination':'/downloads'}]})
    if change=='vpn_restart':child.labels['dk.fjordseed.vpn-generation']='vpn-id:yesterday'
    if change=='image':child.attrs['Image']='old-image'
    if change=='storage':child.attrs['Mounts'][1]['Source']='/old/downloads'
    if change=='uid':child.attrs['Config']['User']='2000:2000'
    runtime.child.return_value=child
    runtime.reconcile()
    child.stop.assert_called_once();child.remove.assert_called_once()
    runtime.client.containers.create.assert_called_once()


def test_unavailable_or_unsafe_vpn_stops_child(runtime):
    child=Mock(status='running')
    runtime.child.return_value=child
    runtime.vpn.attrs['Config']['Env'].append('FIREWALL=off')
    runtime.tick()
    child.stop.assert_called_once()
    runtime.client.containers.create.assert_not_called()
    assert runtime.error
    runtime.discover.side_effect=RuntimeError('Docker unavailable')
    runtime.tick()
    assert child.stop.call_count==2


def test_foreign_seedbox_and_tcp_relay_are_rejected(runtime):
    runtime.client.containers.list.return_value=[Mock(labels={OWNER:'someone-else'})]
    with pytest.raises(ValueError):runtime.reconcile()
    runtime.client.containers.create.assert_not_called()
    runtime.discover.return_value[1][0]['relay_enabled']=True
    with pytest.raises(ValueError):runtime.configure({'profile_id':'a'*32,'enabled':True})


def test_vpn_heartbeat_continues_while_conversion_maintenance_is_blocked(runtime, monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    first_tick, second_tick = threading.Event(), threading.Event()
    advance, stopped = threading.Event(), threading.Event()

    def slow_conversion(_runtime):
        entered.set()
        assert release.wait(5), 'test did not release conversion work'

    monkeypatch.setattr('converter_runtime.sync', slow_conversion)
    runtime.reconcile = Mock(side_effect=lambda: (second_tick if runtime.reconcile.call_count >= 2 else first_tick).set())

    class ControlledStop:
        def is_set(self):
            return stopped.is_set()
        def wait(self, interval):
            assert interval == 3
            advance.wait(5)
            advance.clear()
            return stopped.is_set()

    maintenance = threading.Thread(target=runtime.sync_conversion)
    heartbeat = threading.Thread(target=runtime.run, args=(ControlledStop(),))
    try:
        maintenance.start()
        assert entered.wait(2)
        heartbeat.start()
        assert first_tick.wait(2), 'slow maintenance blocked the VPN heartbeat'
        advance.set()
        assert second_tick.wait(2), 'VPN heartbeat did not refresh again'
        assert not release.is_set()
        assert maintenance.is_alive()
        assert runtime.error == ''
    finally:
        stopped.set(); advance.set(); release.set()
        if heartbeat.ident is not None: heartbeat.join(2)
        maintenance.join(2)
    assert not heartbeat.is_alive()
    assert not maintenance.is_alive()


def test_conversion_failure_does_not_stop_seedbox(runtime, monkeypatch):
    monkeypatch.setattr('converter_runtime.sync', Mock(side_effect=RuntimeError('GPU unavailable')))
    runtime.stop = Mock()
    runtime.sync_conversion()
    runtime.stop.assert_not_called()
    assert runtime.conversion_error
