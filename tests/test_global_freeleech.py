import io
import json
import time
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app import create_app
from benefits import ratio_estimate
from test_app import FakeRuntime, login
from torrent_meta import torrent_meta
from trackers import Trackers

CONFIG={'provider':'nordicbytes','name':'Demo','api_key':'fixture-api-key-not-real'}
NOW=1_800_000_000


def iso(stamp):
    return datetime.fromtimestamp(stamp,timezone.utc).isoformat()


def setup_global(tmp_path,events=None):
    trackers=Trackers(tmp_path)
    ident=trackers.save(CONFIG)
    trackers.cache[ident]={'status':'ok','updated_at':NOW,
        'events':events if events is not None else [{'type':'global_freeleech','ends_at':iso(NOW+30)}],
        'stats':{'uploaded':10,'downloaded':5}}
    result={'status':'matched','matches':[{'tracker_id':ident,'freeleech':25,'double_upload':False}]}
    return trackers,ident,result


def test_active_global_freeleech_overrides_only_download_and_ratio(tmp_path):
    trackers,ident,base=setup_global(tmp_path)
    result=trackers.benefits.with_global(base,now=NOW)
    match=result['matches'][0]
    assert match['freeleech']==100 and match['global_freeleech'] is True
    assert match['torrent_freeleech']==25 and match['double_upload'] is False
    assert base['matches'][0]['freeleech']==25
    estimate=ratio_estimate(match,trackers.cache[ident],100,now=NOW)
    assert estimate['charged_download']==0 and estimate['projected_ratio']==2
    # Even a result containing the active overlay must revert exactly at expiry.
    expired=trackers.benefits.with_global(result,now=NOW+30)['matches'][0]
    assert expired['freeleech']==25 and expired['global_freeleech'] is False
    assert 'global_freeleech_ends_at' not in expired


@pytest.mark.parametrize('events,active',[
    ([],False),
    ([{'type':'movie_club','title':'Global freeleech','ends_at':iso(NOW+100)}],False),
    ([{'type':'global_freeleech','ends_at':iso(NOW)}],False),
    ([{'type':'global_freeleech','starts_at':iso(NOW+1),'ends_at':iso(NOW+100)}],False),
    ([{'type':'global_freeleech','ends_at':'invalid'}],None),
    ([{'type':'global_freeleech','ends_at':'2027-01-01T00:00:00'}],None),
    ([{'type':'global_freeleech'}],None),
    ([{'type':'global_freeleech','starts_at':iso(NOW+100),'ends_at':iso(NOW+50)}],None),
    ([{'type':'global_freeleech','starts_at':iso(NOW),'ends_at':iso(NOW+1)}],True),
])
def test_only_typed_active_events_with_valid_dates_apply(tmp_path,events,active):
    trackers,_,base=setup_global(tmp_path,events)
    match=trackers.benefits.with_global(base,now=NOW)['matches'][0]
    assert match['global_freeleech'] is active
    assert match['freeleech']==(100 if active else 25)


@pytest.mark.parametrize('change',[
    {'status':'error'}, {'updated_at':NOW-121}, {'updated_at':NOW+1}, {'updated_at':float('nan')},
])
def test_failed_stale_or_future_account_never_grants_global_freeleech(tmp_path,change):
    trackers,ident,base=setup_global(tmp_path)
    trackers.cache[ident].update(change)
    match=trackers.benefits.with_global(base,now=NOW)['matches'][0]
    assert match['freeleech']==25 and match['global_freeleech'] is None


def test_accounts_are_isolated_and_existing_full_freeleech_survives_expiry(tmp_path):
    trackers,_,base=setup_global(tmp_path)
    base['matches'].append({'tracker_id':'another','freeleech':0})
    result=trackers.benefits.with_global(base,now=NOW)
    assert result['matches'][1]==base['matches'][1]
    base['matches'][0]['freeleech']=100
    assert trackers.benefits.with_global(base,now=NOW+31)['matches'][0]['freeleech']==100


def test_snapshot_does_not_freeze_global_event(tmp_path,monkeypatch):
    trackers,ident,base=setup_global(tmp_path)
    base['matches'][0].update(tracker_provider='nordicbytes',created_at=None,poster=None)
    monkeypatch.setattr('benefits.time.time',lambda:NOW)
    trackers.benefits.request=Mock(return_value=trackers.benefits.with_global(base))
    meta={'hashes':['a'*40],'name':'Release'}
    assert trackers.benefits.snapshot(meta)['matches'][0]['freeleech']==100
    saved=json.loads(trackers.benefits.snapshot_path.read_text())['a'*40]
    assert saved==base
    monkeypatch.setattr('benefits.time.time',lambda:NOW+31)
    match=trackers.benefits.snapshot(meta)['matches'][0]
    assert match['freeleech']==25 and match['global_freeleech'] is False
    trackers.benefits.request.assert_called_once()


def test_preview_uses_global_event_and_cached_lookup_updates_when_event_ends(tmp_path,monkeypatch):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    client,headers=login(app)
    trackers=app.extensions['trackers'];ident=trackers.save(CONFIG)
    now=int(time.time())
    trackers.cache[ident]={'status':'ok','updated_at':now,'stats':{'uploaded':10,'downloaded':5},
        'events':[{'type':'global_freeleech','ends_at':iso(now+20)}]}
    raw=b'd4:infod4:name1:x6:lengthi15eee'
    meta=torrent_meta(raw)
    trackers.benefits.request(meta)
    cached=next(iter(trackers.benefits.cache.values()))
    cached['result']={'status':'matched','matches':[{'tracker_id':ident,'freeleech':0}]}
    def preview():
        return client.post('/api/torrents/preview',headers=headers,
            data={'torrent':(io.BytesIO(raw),'demo.torrent')}).json
    result=preview()
    assert result['matches'][0]['global_freeleech'] is True
    assert result['ratio_estimates'][0]['charged_download']==0
    monkeypatch.setattr('benefits.time.time',lambda:now+20)
    result=preview()
    assert result['matches'][0]['freeleech']==0
    assert result['ratio_estimates'][0]['charged_download']==15
    app.extensions['runtime'].rpc.assert_not_called()


def test_account_fetch_preserves_typed_global_event_without_title(tmp_path,monkeypatch):
    event={'type':'global_freeleech','ends_at':iso(NOW+100)}
    monkeypatch.setattr(Trackers,'read_json',Mock(return_value={'stats':{},'events':{'global':[event]}}))
    data=Trackers.fetch(CONFIG)
    assert data['events'][0]['type']=='global_freeleech'
    assert data['events'][0]['title']=='Global freeleech'
    assert data['events'][0]['ends_at']==event['ends_at']


def test_rss_rechecks_global_expiry_before_starting(tmp_path):
    from rss_gate import badges_match
    trackers,ident,base=setup_global(tmp_path)
    base['checked_at']=NOW
    result=trackers.benefits.with_global(base,now=NOW)
    result['matches'][0]['global_freeleech_ends_at']=iso(NOW+5)
    feed={'required_badges':['freeleech'],'tracker_id':ident}
    assert badges_match(result,feed,now=NOW+4)
    assert not badges_match(result,feed,now=NOW+5)
    # The torrent's own permanent 100% discount is still valid after the event.
    result['matches'][0]['torrent_freeleech']=100
    assert badges_match(result,feed,now=NOW+5)
