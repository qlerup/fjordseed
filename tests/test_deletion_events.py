import json
from unittest.mock import Mock
import pytest
import download_storage
from deletion_events import delete_completed, confirm_deletions, directory
from event_notifier import EventNotifier
from test_event_notifier import Hub


def test_receipt_requires_torrent_and_file_removal_and_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(download_storage, 'CONFIG', tmp_path/'qbit')
    content=tmp_path/'original.mkv'; content.write_text('data')
    row={'hash':'a'*40,'added_on':100,'name':'Film.1080p.mkv','content_path':str(content)}
    credit={'ratio':1.5,'ratio_limit':1,'seeding_time':200}
    api=Mock()
    assert delete_completed(api,row,credit)
    path=next(directory().glob('*.json'))
    event=json.loads(path.read_text())['event']
    assert event['reason']=='ratio' and event['ratio_limit']==1
    confirm_deletions([row]); assert not json.loads(path.read_text())['ready']
    confirm_deletions([]); assert not json.loads(path.read_text())['ready']
    content.unlink()
    confirm_deletions([]); assert json.loads(path.read_text())['ready']
    hub=Hub(); hub.fail=True
    EventNotifier(tmp_path,hub,'fjordseed').flush()
    assert path.exists()
    hub.fail=False
    EventNotifier(tmp_path,hub,'fjordseed').flush()
    assert not path.exists() and hub.calls[0][1]==event
    EventNotifier(tmp_path,hub,'fjordseed').flush()
    assert len(hub.calls)==1


def test_failed_delete_does_not_notify(tmp_path):
    api=Mock(side_effect=OSError('failed'))
    with pytest.raises(OSError):
        delete_completed(api,{'hash':'b'*40,'name':'Failed'}, {'ratio':0,'ratio_limit':1})
    assert not list(directory().glob('*.json'))


@pytest.mark.parametrize('converted,hours,target',[(False,53,2),(True,49,1)])
def test_time_reason_and_conversion_goal(converted,hours,target):
    row={'hash':'c'*40,'name':'Show.S01E01','added_on':200}
    credit={'ratio':.5,'ratio_limit':2,'extra_seed_hours':4,'seeding_time':53*3600}
    delete_completed(Mock(),row,credit,converted=converted)
    event=json.loads(next(directory().glob('*.json')).read_text())['event']
    assert event['reason']=='time' and event['seed_hours']==hours and event['ratio_limit']==target
    assert event['library_retained'] is converted


def test_no_receipt_for_disappearing_manual_torrent():
    confirm_deletions([])
    assert not list(directory().glob('*.json'))


def test_id_stable_on_retry_but_new_for_readded_torrent():
    row={'hash':'d'*40,'name':'Again','added_on':1}
    credit={'ratio':1,'ratio_limit':1}
    delete_completed(Mock(),row,credit)
    delete_completed(Mock(),row,credit)
    assert len(list(directory().glob('*.json')))==1
    delete_completed(Mock(),dict(row,added_on=2),credit)
    assert len(list(directory().glob('*.json')))==2


def test_allocated_size_sparse_and_hardlinks(tmp_path):
    import os
    from deletion_events import releasable_bytes
    content=tmp_path/'content';content.mkdir()
    original=content/'original'; original.write_bytes(b'x'*10000)
    blocks=original.stat().st_blocks*512
    assert releasable_bytes(str(original))==blocks
    os.link(original,content/'internal')
    assert releasable_bytes(str(content))==blocks
    os.link(original,tmp_path/'retained')
    assert releasable_bytes(str(content))==0
    with (content/'sparse').open('wb') as f:f.truncate(10**9)
    sparse=(content/'sparse').stat().st_blocks*512
    assert releasable_bytes(str(content))==sparse
    (content/'link').symlink_to(tmp_path/'retained')
    assert releasable_bytes(str(content))==sparse


def test_unknown_measurement_and_saved_size(tmp_path):
    from deletion_events import releasable_bytes
    assert releasable_bytes(None) is None
    assert releasable_bytes(str(tmp_path/'missing')) is None
    content=tmp_path/'movie';content.write_bytes(b'x'*5000)
    expected=content.stat().st_blocks*512
    delete_completed(Mock(),{'hash':'a'*40,'name':'Movie','content_path':str(content)}, {'ratio':1,'ratio_limit':1})
    path=next(directory().glob('*.json'))
    content.unlink();confirm_deletions([])
    receipt=json.loads(path.read_text())
    assert receipt['ready'] and receipt['event']['freed_bytes']==expected


def test_final_transfer_totals_survive_deletion_and_delivery(tmp_path, monkeypatch):
    monkeypatch.setattr(download_storage,'CONFIG',tmp_path/'qbit')
    content=tmp_path/'file';content.write_text('original')
    row={'hash':'e'*40,'name':'Episode','content_path':str(content),'uploaded':10,'ratio':.01}
    credit={'uploaded':2350000000,'client_uploaded':10,'credited_uploaded':1175000000,'ratio':2.35,'ratio_limit':2}
    delete_completed(Mock(),row,credit)
    content.unlink();confirm_deletions([])
    hub=Hub();EventNotifier(tmp_path,hub,'fjordseed').flush()
    assert hub.calls[0][1]['transfer']=={'uploaded':2350000000,'credited_uploaded':1175000000,'ratio':2.35}
    assert hub.calls[0][1]['ratio_limit']==2


@pytest.mark.parametrize('value',[None,-1,True,float('nan'),float('inf'),'123'])
def test_invalid_or_unknown_transfer_remains_unknown(value):
    delete_completed(Mock(),{'hash':'f'*40,'name':'Unknown'},
                     {'ratio_limit':1,'ratio':0,'uploaded':value,'credited_uploaded':value})
    transfer=json.loads(next(directory().glob('*.json')).read_text())['event']['transfer']
    assert transfer=={'uploaded':None,'credited_uploaded':None,'ratio':0}
