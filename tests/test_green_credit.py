import json
from unittest.mock import Mock

import pytest
import green_credit as credit
from qbit_rpc import execute, sync_share_limits, stop_requirement

HASH='a'*40
CREATED=1_700_000_000
END=CREATED+24*3600+1800


def policy(until=END,known=True):
    credit.POLICIES.write_text(json.dumps({HASH:{'until':until,'known':known},'_enabled':True}))


def row(uploaded=0,ratio_limit=1,**extra):
    return {'hash':HASH,'uploaded':uploaded,'downloaded':1000,'ratio':uploaded/1000,
            'ratio_limit':ratio_limit,'added_on':CREATED+60,'state':'stalledUP',
            'seeding_time_limit':2940,'inactive_seeding_time_limit':-1,**extra}


def update(value,now,target=None):
    with credit.CreditLedger().transaction() as ledger:
        return ledger.update(value,now=now,target=target)


@pytest.mark.parametrize('target',[1,2,5])
def test_green_requires_double_upload_for_selected_goal(target):
    policy()
    result=update(row(1000),CREATED+120,target)
    assert result['native_ratio_limit']==target*2
    assert result['credited_ratio']==.5
    assert result['ratio_limit']==target
    result=update(row(target*2000),CREATED+130)
    assert result['credited_ratio']==target


def test_buffer_and_mixed_upload_survive_restart_and_goal_edit():
    policy()
    first=update(row(1000),CREATED+24*3600+1799)
    assert first['green_active'] and first['credited_uploaded']==500
    # At expiry old upload is not retroactively credited. A crossing sample
    # with no new bytes introduces no rounding/estimation difference.
    expiry=update(row(1000,2),END)
    assert not expiry['green_active'] and expiry['native_ratio_limit']==1.5
    full=update(row(1500,1.5),END+10)
    assert full['green_uploaded']==1000 and full['credited_uploaded']==1000
    assert full['credited_ratio']==1 and full['ratio_limit']==1
    changed=update(row(1500,1.5),END+20,target=5)
    assert changed['native_ratio_limit']==5.5 and changed['credited_ratio']==1
    assert update(row(1600,5.5),END+30)['credited_uploaded']==1100


def test_crossing_interval_is_conservative():
    policy()
    update(row(1000),END-5)
    crossed=update(row(1100),END+5)
    assert crossed['credited_uploaded']==550
    assert update(row(1200),END+15)['credited_uploaded']==650


def test_existing_historical_upload_is_not_falsely_credited_in_full():
    policy()
    result=update(row(1000),END+86400)
    assert result['credited_uploaded']==500 and result['green_history_estimated']
    result=update(row(2000,added_on=END+10),END+20)
    assert result['green_uploaded']==0


def test_older_torrent_added_after_expiry_uses_full_credit():
    policy()
    result=update(row(1000,added_on=END+1),END+20)
    assert result['credited_ratio']==1 and result['native_ratio_limit']==1


def test_pending_lookup_keeps_upload_bytes_and_later_classifies():
    policy(None,False)
    pending=update(row(1000),CREATED+100)
    assert pending['green_pending'] and pending['native_ratio_limit']==2
    assert pending['credited_uploaded']==500
    policy()
    verified=update(row(1100),CREATED+110)
    assert verified['credited_uploaded']==550 and verified['green_uploaded']==1100


def test_non_green_lookup_releases_conservative_pending_goal():
    policy(None,False)
    update(row(1000),CREATED+100)
    policy(None,True)
    credit.POLICIES.write_text(json.dumps({HASH:{'until':None,'known':True,'has_date':True},'_enabled':True}))
    result=update(row(1100),CREATED+110)
    assert result['credited_uploaded']==1100 and result['native_ratio_limit']==1


def test_failed_date_lookup_cannot_allow_premature_stop():
    verified=credit.policy_from_result({'status':'unavailable','matches':[]})
    credit.POLICIES.write_text(json.dumps({HASH:verified,'_enabled':True}))
    result=update(row(1000),CREATED+120)
    assert result['green_pending'] and result['green_date_unavailable']
    assert result['native_ratio_limit']==2 and result['credited_ratio']==.5
    assert not stop_requirement({**row(1000),**result})['seeding_requirement_met']


def test_pending_lookup_for_old_torrent_does_not_discount_new_upload():
    policy(None,False)
    update(row(1000,added_on=END+10),END+20)
    policy()
    result=update(row(1100,added_on=END+10),END+30)
    assert result['credited_uploaded']==1100 and result['green_uploaded']==0


def test_native_rss_keeps_user_goal_and_existing_edits():
    policy(None,False)
    credit.POLICIES.write_text(json.dumps({HASH:{'until':END,'known':True},'_enabled':True,'_started_at':CREATED}))
    credit.CONFIG.mkdir()
    (credit.CONFIG/'fjord-rss.json').write_text(json.dumps([{'id':'b'*32,'ratio_limit':5}]))
    tags='Other, FjordSeed-RSS-'+'b'*32
    fresh=update(row(1000,10,tags=tags),CREATED+120)
    assert fresh['ratio_limit']==5 and fresh['native_ratio_limit']==10
    old=update(row(1000,3,hash='c'*40,tags=tags,added_on=CREATED-100),CREATED+120)
    assert old['ratio_limit']==3  # Never overwrite an older per-torrent edit.


def test_api_ratio_edit_preserves_credit_action_and_paused_state(monkeypatch):
    policy()
    calls=[]
    def api(path,data=None):
        calls.append((path,data))
        return Mock(json=lambda: {'current_network_interface':'tun0','upnp':False} if path=='app/preferences'
                    else [row(1000,share_limit_action='RemoveWithContent',state='stoppedUP')])
    monkeypatch.setattr('qbit_rpc.call',api)
    monkeypatch.setattr(credit.time,'time',lambda:CREATED+120)
    execute('ratio',{'hash':HASH,'ratio_limit':5})
    assert calls[-1][1]['ratioLimit']==-1
    assert calls[-1][1]['shareLimitAction']=='RemoveWithContent'
    assert not any(p in ('torrents/start','torrents/stop') for p,_ in calls)
    assert update(row(1000,10),CREATED+130)['ratio_limit']==5


def test_worker_adjusts_after_expiry_and_keeps_49_hour_alternative(monkeypatch):
    policy()
    update(row(1000),END-1)
    monkeypatch.setattr(credit.time,'time',lambda:END+10)
    calls=[]
    def api(path,data=None):
        calls.append((path,data))
        return Mock(json=lambda:[row(1000,2,share_limit_action='RemoveWithContent')])
    sync_share_limits(api)
    assert calls[-1][1]['ratioLimit']==-1
    assert calls[-1][1]['seedingTimeLimit']==-1
    assert calls[-1][1]['shareLimitAction']=='RemoveWithContent'
    effective=update(row(1000,1.5),END+10)
    assert not stop_requirement({**row(1000),**effective})['seeding_requirement_met']
    effective=update(row(1000,seeding_time=49*3600),END+20)
    assert stop_requirement({**row(1000,seeding_time=49*3600),**effective})['seeding_requirement_met']


def test_policy_uses_verified_created_at_and_uploader_exception():
    match={'tracker_provider':'nordicbytes','created_at':'2023-11-14T22:13:20.000000Z'}
    assert credit.policy_from_result({'status':'matched','matches':[match]})=={'until':END,'known':True,'has_date':True}
    assert credit.policy_from_result({'status':'matched','matches':[{**match,'own_upload':True}]})['until'] is None
    for value in (None,'bad','2023-11-14T22:13:20'):
        assert credit.created_timestamp(value) is None


def test_corrupt_ledger_does_not_silently_discard_upload_history():
    credit.CONFIG.mkdir()
    (credit.CONFIG/'green-credit.json').write_text('{broken')
    with pytest.raises(ValueError): update(row(1000),END+10)


def test_saved_badges_get_one_date_migration_without_live_refresh(tmp_path):
    from trackers import Trackers
    trackers=Trackers(tmp_path)
    ident=trackers.save({'provider':'nordicbytes','name':'Fixture','api_key':'fixture-not-real-key'})
    benefits=trackers.benefits
    meta={'hashes':[HASH],'name':'Linux'}
    old={'status':'matched','matches':[{'tracker_id':ident,'freeleech':100}]}
    benefits.remember(meta,old)
    new={'status':'matched','matches':[{**old['matches'][0],'tracker_provider':'nordicbytes',
        'created_at':'2023-11-14T22:13:20Z','poster':None}]}
    benefits.request=Mock(return_value=new)
    assert benefits.snapshot(meta)==new
    assert benefits.snapshot(meta)==new
    benefits.request.assert_called_once()
    published=json.loads((tmp_path/'rpc'/'green-policy.json').read_text())
    assert published[HASH]['until']==END
    assert 'api_key' not in json.dumps(published)


def test_manual_add_protects_goal_before_async_date_lookup(monkeypatch):
    policy(None,False)
    calls=[]
    def api(path,data=None,files=None):
        calls.append((path,data))
        return Mock(json=lambda:{'current_network_interface':'tun0','upnp':False},text='Ok.')
    monkeypatch.setattr('qbit_rpc.call',api)
    execute('add',{'magnet':'magnet:?xt=urn:btih:'+HASH+'&dn=Linux','ratio_limit':1})
    assert calls[-1][1]['ratioLimit']==-1
    result=update(row(1000,2),CREATED+120)
    assert result['ratio_limit']==1 and result['credited_ratio']==.5


FEED='b'*32
OTHER_FEED='c'*32


def feed_totals():
    return json.loads((credit.CONFIG/'green-credit.json').read_text())['_rss_upload']['feeds']


def test_feed_credit_tracks_green_expiry_without_double_counting():
    policy()
    tags='other, FjordSeed-RSS-'+FEED
    assert update(row(1000,tags=tags),CREATED+120)['credited_uploaded']==500
    update(row(1000,tags=tags),CREATED+130)
    assert feed_totals()[FEED]['credited_uploaded']==500
    update(row(1200,tags=tags),END+10)
    update(row(1400,tags=tags),END+20)
    assert feed_totals()[FEED]['credited_uploaded']==800
    # Same feed, a second torrent; a manual torrent and other feed stay separate.
    policies=json.loads(credit.POLICIES.read_text())
    policies.update({h*40:{'known':True,'until':None,'has_date':True} for h in ('d','e','f')})
    credit.POLICIES.write_text(json.dumps(policies))
    update(row(200,hash='d'*40,tags=tags),END+20)
    update(row(900,hash='e'*40),END+20)
    update(row(300,hash='f'*40,tags='FjordSeed-RSS-'+OTHER_FEED),END+20)
    assert feed_totals()[FEED]['credited_uploaded']==1000
    assert feed_totals()[OTHER_FEED]['credited_uploaded']==300


def test_feed_credit_survives_torrent_removal_restart_and_readdition():
    policy(None)
    tags='FjordSeed-RSS-'+FEED
    update(row(1000,tags=tags),END+10)
    with credit.CreditLedger().transaction() as ledger:
        ledger.entries.pop(HASH)
    assert feed_totals()[FEED]['credited_uploaded']==1000
    update(row(200,tags=tags,added_on=END+15),END+20)
    update(row(200,tags=tags,added_on=END+15),END+25)
    assert feed_totals()[FEED]['credited_uploaded']==1200
    # Counter reset cannot subtract upload already earned by this feed.
    update(row(50,tags=tags,added_on=END+15),END+30)
    assert feed_totals()[FEED]['credited_uploaded']==1250
    update(row(100,tags=tags,added_on=END+15),END+35)
    assert feed_totals()[FEED]['credited_uploaded']==1300


def test_feed_credit_adjusts_pending_classification():
    tags='FjordSeed-RSS-'+FEED
    policy(None,False)
    update(row(1000,tags=tags),CREATED+120)
    assert feed_totals()[FEED]['credited_uploaded']==500
    assert feed_totals()[FEED]['estimated'] is True
    policy(None,True)
    update(row(1000,tags=tags),CREATED+130)
    assert feed_totals()[FEED]['credited_uploaded']==1000
    update(row(1000,tags=tags),CREATED+140)
    assert feed_totals()[FEED]['credited_uploaded']==1000


def test_feed_credit_new_incarnation_retains_old_total():
    policy(None)
    tags='FjordSeed-RSS-'+FEED
    update(row(1000,tags=tags),END+10)
    update(row(200,tags=tags,added_on=END+15),END+20)
    assert feed_totals()[FEED]['credited_uploaded']==1200


def test_feed_credit_imports_available_old_upload_once():
    policy(None)
    update(row(1000),END+10)
    path=credit.CONFIG/'green-credit.json'
    saved=json.loads(path.read_text())
    saved.pop('_rss_upload')
    path.write_text(json.dumps(saved))
    update(row(1200,tags='FjordSeed-RSS-'+FEED),END+20)
    update(row(1200,tags='FjordSeed-RSS-'+FEED),END+30)
    assert feed_totals()[FEED]['credited_uploaded']==1200
