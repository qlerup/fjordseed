import json
import threading
from unittest.mock import Mock

from trackers import Trackers
from green_credit import GREEN_SECONDS, created_timestamp, CreditLedger
import green_credit

HASH='a'*40
META={'hashes':[HASH],'name':'Release'}
CONFIG={'provider':'nordicbytes','name':'Demo','api_key':'fixture-not-real-key'}
FAILED={'status':'unavailable','matches':[]}


def setup(tmp_path,monkeypatch):
    clock=[1_800_000_000.0]
    monkeypatch.setattr('benefits.time.time',lambda:clock[0])
    trackers=Trackers(tmp_path);ident=trackers.save(CONFIG)
    return trackers,ident,clock


def run_one(benefits,result):
    stop=threading.Event()
    def lookup(*args):
        stop.set();return result
    benefits.lookup=Mock(side_effect=lookup)
    benefits.run(stop)
    benefits.lookup.assert_called_once()


def complete(ident,**changes):
    return {'status':'matched','matches':[{'tracker_id':ident,'tracker_provider':'nordicbytes',
        'created_at':'2027-01-15T08:00:00Z','freeleech':100,'double_upload':False,
        'poster':'https://image.tmdb.org/t/p/w500/fixture.jpg',**changes}]}


def test_initial_failure_then_exactly_three_retries_two_minutes_apart(tmp_path,monkeypatch):
    trackers,_,clock=setup(tmp_path,monkeypatch);b=trackers.benefits
    assert b.snapshot(META)['status']=='pending'
    run_one(b,FAILED)
    assert b.retries[HASH]['count']==0
    for count in range(1,4):
        clock[0]+=119
        for _ in range(4):b.snapshot(META)
        assert b.jobs.empty() and b.retries[HASH]['count']==count-1
        clock[0]+=1
        b.snapshot(META)
        assert b.jobs.qsize()==1 and b.retries[HASH]['count']==count
        for _ in range(4):b.snapshot(META)
        assert b.jobs.qsize()==1
        run_one(b,FAILED)
    clock[0]+=86400
    for _ in range(10):b.snapshot(META)
    assert b.jobs.empty() and b.retries[HASH]['count']==3


def test_retry_limit_and_interval_survive_restart_and_manual_refresh_resets(tmp_path,monkeypatch):
    trackers,_,clock=setup(tmp_path,monkeypatch);b=trackers.benefits
    b.remember(META,FAILED)
    for count in range(1,4):
        clock[0]+=120
        b=Trackers(tmp_path).benefits
        b.snapshot(META)
        assert b.retries[HASH]['count']==count
        run_one(b,FAILED)
    clock[0]+=120
    b=Trackers(tmp_path).benefits
    b.snapshot(META)
    assert b.jobs.empty()
    assert b.refresh_snapshot(META)['status']=='pending'
    run_one(b,FAILED)
    assert b.retries[HASH]['count']==0


def test_pending_retry_restart_does_not_duplicate_or_reset_budget(tmp_path,monkeypatch):
    trackers,_,clock=setup(tmp_path,monkeypatch);b=trackers.benefits
    b.remember(META,FAILED)
    clock[0]+=120;b.snapshot(META)
    assert b.retries[HASH]['in_flight'] is True
    restored=Trackers(tmp_path).benefits
    restored.snapshot(META)
    assert restored.jobs.empty() and restored.retries[HASH]['count']==1
    clock[0]+=120;restored.snapshot(META)
    assert restored.jobs.qsize()==1 and restored.retries[HASH]['count']==2


def test_success_updates_freeleech_green_and_worker_policy_then_stops_retrying(tmp_path,monkeypatch):
    trackers,ident,clock=setup(tmp_path,monkeypatch);b=trackers.benefits
    b.remember(META,FAILED)
    clock[0]+=120;b.snapshot(META)
    found=complete(ident)
    run_one(b,found)
    assert b.snapshot(META)['matches'][0]['freeleech']==100
    assert HASH not in b.retries
    policy=json.loads((tmp_path/'rpc'/'green-policy.json').read_text())
    expected=created_timestamp(found['matches'][0]['created_at'])+GREEN_SECONDS
    assert policy[HASH]['until']==expected and policy[HASH]['has_date'] is True
    # The same published policy is consumed by worker accounting without a restart.
    monkeypatch.setattr(green_credit,'POLICIES',tmp_path/'rpc'/'green-policy.json')
    with CreditLedger().transaction() as ledger:
        row={'hash':HASH,'uploaded':1000,'downloaded':1000,'ratio':1,'ratio_limit':1,
             'added_on':clock[0]-10,'seeding_time':10,'state':'uploading'}
        result=ledger.update(row,now=clock[0])
    assert result['green_pending'] is False
    assert result['green_until']==expected
    clock[0]+=86400;b.snapshot(META)
    assert b.jobs.empty()


def test_partial_match_gets_missing_fields_without_overwriting_known_green(tmp_path,monkeypatch):
    trackers,ident,clock=setup(tmp_path,monkeypatch);b=trackers.benefits
    old=complete(ident,freeleech=None,double_upload=None,poster=None)
    b.remember(META,old)
    clock[0]+=120;b.snapshot(META)
    run_one(b,complete(ident,created_at='2027-01-16T09:00:00Z'))
    match=b.snapshots[HASH]['matches'][0]
    assert match['created_at']==old['matches'][0]['created_at']
    assert match['freeleech']==100 and match['double_upload'] is False and match['poster']
    assert HASH not in b.retries


def test_missing_green_date_is_enriched_even_when_key_was_already_present(tmp_path,monkeypatch):
    trackers,ident,clock=setup(tmp_path,monkeypatch);b=trackers.benefits
    b.remember(META,complete(ident,created_at=None))
    clock[0]+=120;b.snapshot(META)
    run_one(b,complete(ident))
    assert b.snapshots[HASH]['matches'][0]['created_at'] is not None
    assert HASH not in b.retries


def test_complete_or_unconfigured_torrents_do_not_retry(tmp_path,monkeypatch):
    trackers,ident,clock=setup(tmp_path,monkeypatch);b=trackers.benefits
    b.remember(META,complete(ident));clock[0]+=120
    b.snapshot(META)
    assert b.jobs.empty() and not b.retries
    trackers.remove(ident)
    b.remember({'hashes':['b'*40]},FAILED)
    assert 'b'*40 not in b.retries
