import json
from datetime import datetime,timezone
from unittest.mock import Mock
import pytest
from tracker_credit import accrue,policy
from green_credit import CreditLedger
import green_credit as credit
from trackers import Trackers

H='a'*40
F='b'*32


def rules(**changes):
    return dict(green_until=86400,double_upload=False,freeleech=0,checked_at=100,**changes)


@pytest.mark.parametrize('green,double,expected',[(86400,False,50),(86400,True,100),(0,False,100),(0,True,200)])
def test_green_and_double_multiply(green,double,expected):
    state={};r=rules();r.update(green_until=green,double_upload=double)
    assert accrue(state,100,200,100,110,r)==(expected,200)
    assert not state['pending']


def test_exact_24_hour_cutoff_and_crossing_interval():
    date=datetime.fromtimestamp(100,timezone.utc).isoformat()
    p=policy({'status':'matched','checked_at':86500,'matches':[{'created_at':date,'double_upload':True,'freeleech':50}]})
    assert p['green_until']==86500
    p['checked_at']=86490
    state={}
    assert accrue(state,100,100,86490,86510,p)==(150,50)
    assert state['estimated']
    assert accrue(state,100,100,86510,86520,p)==(200,50)


def test_pending_lookup_is_persistable_and_resolves_short_gap():
    state={};assert accrue(state,100,100,100,110,{})==(0,0)
    restored=json.loads(json.dumps(state));r=rules();r.update(checked_at=120,freeleech=100)
    assert accrue(restored,0,0,110,120,r)==(50,0)
    assert not restored['pending'] and restored['estimated']


def test_old_unknown_is_not_reclassified_by_new_flags():
    state={};accrue(state,100,100,100,110,{})
    r=rules();r.update(checked_at=1000)
    assert accrue(state,0,0,110,1000,r)==(0,0)
    assert state['unknown_uploaded']==100 and state['unknown_downloaded']==100


def test_missing_upload_flags_does_not_block_known_freeleech():
    state={};r=rules();r['double_upload']=None
    assert accrue(state,100,100,100,110,r)==(0,100)
    assert state['pending'][0]['uploaded']==100 and not state['pending'][0]['downloaded']


def test_global_freeleech_expiry():
    state={};r=rules();r.update(global_until=105,freeleech=50)
    assert accrue(state,0,100,100,110,r)==(0,25)


def test_archive_restart_counter_rollback_and_removed_pending(tmp_path,monkeypatch):
    monkeypatch.setattr(credit,'CONFIG',tmp_path/'qbit')
    monkeypatch.setattr(credit,'POLICIES',tmp_path/'green-policy.json')
    path=tmp_path/'tracker-credit.json'
    path.write_text(json.dumps({'_version':1,H:rules()}))
    row=dict(hash=H,name='Show.S01E01',tags='FjordSeed-RSS-'+F,uploaded=100,downloaded=200,added_on=100)
    with CreditLedger().transaction() as ledger:ledger.update(row,now=110)
    with CreditLedger().transaction() as ledger:
        ledger.update(dict(row,uploaded=150,downloaded=300),now=120)
        item=ledger.entries['_rss_upload']['feeds'][F]['downloads'][H]
        assert item['credited_uploaded']==75 and item['credited_downloaded']==300
        ledger.update(dict(row,uploaded=50,downloaded=100),now=130)
        assert item['credited_uploaded']==75
    path.write_text(json.dumps({'_version':1}))
    with CreditLedger().transaction() as ledger:
        ledger.update(dict(row,uploaded=60,downloaded=120),now=140)
        ledger.entries.pop(H)
    path.write_text(json.dumps({'_version':1,H:rules()}))
    monkeypatch.setattr(credit.time,'time',lambda:150)
    with CreditLedger().transaction() as ledger:
        item=ledger.entries['_rss_upload']['feeds'][F]['downloads'][H]
        assert item['credited_uploaded']==80 and item['credited_downloaded']==320
        assert not item['upload_credit_pending']


def test_live_accounting_updates_without_rewriting_frozen_display(tmp_path):
    trackers=Trackers(tmp_path);tid=trackers.save({'name':'Demo','provider':'nordicbytes','api_key':'fixture-not-real-key'})
    benefits=trackers.benefits
    old={'status':'matched','checked_at':100,'matches':[{'tracker_id':tid,'tracker_provider':'nordicbytes','created_at':'2026-10-24T00:00:00Z','freeleech':0,'double_upload':False}]}
    meta={'hashes':[H],'name':'Show'}
    benefits.remember(meta,old)
    new={**old,'checked_at':200,'matches':[{**old['matches'][0],'freeleech':100,'double_upload':True}]}
    benefits.request=Mock(return_value=new);benefits.accounting_poll(meta)
    assert benefits.snapshots[H]['matches'][0]['double_upload'] is False
    published=json.loads((tmp_path/'rpc/tracker-credit.json').read_text())
    assert published[H]['double_upload'] is True and published[H]['freeleech']==100
    restored=Trackers(tmp_path).benefits
    assert restored.accounting[H]['checked_at']==200


def test_enabling_live_rules_preserves_legacy_credit_and_only_adds_new_bytes(tmp_path,monkeypatch):
    monkeypatch.setattr(credit,'CONFIG',tmp_path/'qbit')
    monkeypatch.setattr(credit,'POLICIES',tmp_path/'green-policy.json')
    (tmp_path/'green-policy.json').write_text(json.dumps({H:{'known':True,'until':1000}}))
    row=dict(hash=H,name='Show',tags='FjordSeed-RSS-'+F,uploaded=100,downloaded=200,added_on=100)
    with CreditLedger().transaction() as ledger:ledger.update(row,now=110)
    r=rules();r.update(green_until=0,double_upload=True,checked_at=110)
    (tmp_path/'tracker-credit.json').write_text(json.dumps({'_version':1,H:r}))
    with CreditLedger().transaction() as ledger:
        ledger.update(dict(row,uploaded=200,downloaded=250),now=120)
        item=ledger.entries['_rss_upload']['feeds'][F]['downloads'][H]
        assert item['credited_uploaded']==250  # Original 50 + new 100 * 2.
        assert ledger.entries['_rss_upload']['feeds'][F]['credited_uploaded']==250
        assert item['download_credit_incomplete']  # Earlier flags remain unknown.
