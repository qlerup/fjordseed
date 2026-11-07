import json
import threading
from unittest.mock import Mock

import green_credit
import qbit_rpc
import qbit_worker as worker


def test_live_status_snapshot_does_not_wait_for_conversion_lock(tmp_path,monkeypatch):
    monkeypatch.setattr(green_credit,'CONFIG',tmp_path)
    path=tmp_path/'green-credit.json'
    path.write_text(json.dumps({'saved':{'uploaded':123}}))
    held=threading.Event();release=threading.Event();read=threading.Event()
    def writer():
        with green_credit.CreditLedger().transaction():
            held.set();release.wait(5)
    def reader():
        with green_credit.CreditLedger().snapshot() as ledger:
            assert ledger.entries['saved']['uploaded']==123
            ledger.entries['saved']['uploaded']=999
        read.set()
    owner=threading.Thread(target=writer);viewer=threading.Thread(target=reader)
    owner.start()
    try:
        assert held.wait(2)
        viewer.start()
        assert read.wait(2),'status waited behind conversion ledger lock'
        assert json.loads(path.read_text())['saved']['uploaded']==123
    finally:
        release.set();owner.join(3)
        if viewer.ident:viewer.join(3)
    assert json.loads(path.read_text())['saved']['uploaded']==123


def test_busy_maintenance_process_is_neither_waited_for_nor_duplicated(tmp_path,monkeypatch):
    process=Mock();process.poll.return_value=None
    launch=Mock(return_value=process);monkeypatch.setattr(worker.subprocess,'Popen',launch)
    helper=worker.Maintenance(tmp_path)
    assert helper.snapshot()=={}
    assert helper.snapshot()=={}
    launch.assert_called_once()
    assert launch.call_args.args[0][-1]=='--maintenance'
    process.wait.assert_not_called()
    helper.path.write_text(json.dumps({'rss':[],'ready':False,'checked_at':0,'seeding_error':'policy error'}))
    assert helper.snapshot()=={'rss':[],'seeding_error':'policy error'}


def test_failed_maintenance_launch_is_not_a_vpn_failure(tmp_path,monkeypatch):
    monkeypatch.setattr(worker.subprocess,'Popen',Mock(side_effect=OSError()))
    helper=worker.Maintenance(tmp_path)
    assert helper.snapshot().get('seeding_error')


def test_status_rpc_reads_live_torrents_without_writing_limits_or_ledger(monkeypatch):
    row={'hash':'a'*40,'name':'current torrent','uploaded':123,'downloaded':100,
         'size':100,'progress':1,'state':'uploading','ratio_limit':2,'seeding_time':0}
    def call(path,data=None):
        assert data is None,'status must not mutate qBittorrent'
        values={'app/preferences':{'current_network_interface':'tun0','upnp':False,'listen_port':40001},
                'torrents/info':[row],'transfer/info':{'up_info_speed':123}}
        return Mock(json=lambda:values[path],text='5.1.4')
    monkeypatch.setattr(qbit_rpc,'call',call)
    monkeypatch.setattr(green_credit.CreditLedger,'transaction',Mock(side_effect=AssertionError('writer lock acquired')))
    save=Mock(side_effect=AssertionError('status persisted ledger'))
    monkeypatch.setattr(green_credit.CreditLedger,'save',save)
    result=qbit_rpc.execute('status',{})
    assert result['torrents'][0]['name']=='current torrent'
    assert result['torrents'][0]['uploaded']==123
    assert result['transfer']['up_info_speed']==123


def test_maintenance_restart_discards_previous_generation_status(tmp_path,monkeypatch):
    helper=worker.Maintenance(tmp_path)
    helper.path.write_text(json.dumps({'rss_error':True}))
    helper.process=Mock();helper.process.poll.return_value=1
    new=Mock();new.poll.return_value=None
    monkeypatch.setattr(worker.subprocess,'Popen',Mock(return_value=new))
    assert helper.snapshot()=={}
    assert helper.process is new
    assert not helper.path.exists()


def test_bounded_verification_continues_in_maintenance_process(monkeypatch):
    stop=Mock();stop.is_set.side_effect=[False,False,True]
    monkeypatch.setattr(worker,'STOP',stop)
    monkeypatch.setattr(worker.signal,'signal',Mock())
    monkeypatch.setattr(worker,'ready',Mock())
    checks=Mock(return_value=[]);monkeypatch.setattr(worker,'sync_share_limits',checks)
    monkeypatch.setattr('library_conversion.verification_pending',lambda:True)
    monkeypatch.setattr(worker,'sync_snapshot',Mock())
    monkeypatch.setattr(worker,'rss_report',Mock(return_value=[]))
    monkeypatch.setattr('rss_budget.admission_lock',lambda _:__import__('contextlib').nullcontext())
    monkeypatch.setattr('rss_budget.status',Mock())
    writes=Mock();monkeypatch.setattr(worker,'atomic',writes)
    worker.run_maintenance()
    assert checks.call_count==2
    assert [c.args[0] for c in stop.wait.call_args_list]==[.05,.05]
    assert all('worker-status' not in str(c.args[0]) for c in writes.call_args_list)


def test_policy_errors_are_reported_without_ending_maintenance(monkeypatch):
    stop=Mock();stop.is_set.side_effect=[False,True]
    monkeypatch.setattr(worker,'STOP',stop)
    monkeypatch.setattr(worker.signal,'signal',Mock())
    monkeypatch.setattr(worker,'ready',Mock())
    monkeypatch.setattr('library_conversion.verification_pending',lambda:False)
    monkeypatch.setattr(worker,'sync_share_limits',Mock(side_effect=OSError()))
    monkeypatch.setattr(worker,'sync_snapshot',Mock(side_effect=OSError()))
    writes=Mock();monkeypatch.setattr(worker,'atomic',writes)
    worker.run_maintenance()
    status=json.loads(writes.call_args.args[1])
    assert status['seeding_error'] and status['rss_error']
