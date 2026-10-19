import json
import time
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from app import create_app
from green_credit import GREEN_SECONDS, policy_from_result
from rss_gate import RssGate
from test_app import FakeRuntime, login
from test_trackers import ACCOUNT, KEY
from tracker_providers import PROVIDERS
from trackers import Trackers, TrackerError


@pytest.mark.parametrize('provider', PROVIDERS)
def test_account_uses_own_fixed_host_and_bearer_key(provider, monkeypatch):
    response = Mock(status_code=200)
    response.iter_content.return_value = [json.dumps(ACCOUNT).encode()]
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.get.return_value = response
    monkeypatch.setattr('trackers.requests.Session', Mock(return_value=client))
    entry = {'provider':provider,'api_key':KEY}
    account = Trackers.fetch(entry)
    assert account['stats']['ratio'] == 2
    assert account['stats']['warnings'] == 3
    assert client.get.call_args.args[0] == PROVIDERS[provider]['url']
    assert client.get.call_args.kwargs['headers']['Authorization'] == 'Bearer ' + KEY
    assert client.get.call_args.kwargs['allow_redirects'] is False
    other = 'sagmire' if provider == 'nordicbytes' else 'nordicbytes'
    client.get.reset_mock()
    with pytest.raises(TrackerError):
        Trackers.read_json(entry, PROVIDERS[other]['url'])
    client.get.assert_not_called()


def test_benefits_global_freeleech_and_green_keep_accounts_separate(tmp_path):
    trackers = Trackers(tmp_path)
    now = time.time()
    created = datetime.fromtimestamp(now-60, timezone.utc).isoformat()
    ids = {}
    for provider in PROVIDERS:
        ids[provider] = trackers.save({'provider':provider,'name':provider,'api_key':provider+'-synthetic-key-only'})
        trackers.cache[ids[provider]] = {'status':'ok','updated_at':now,'username':provider,
            'events':[{'type':'global_freeleech','ends_at':datetime.fromtimestamp(now+600,timezone.utc).isoformat()}] if provider == 'sagmire' else []}
    def search(entry, url, params):
        assert url == PROVIDERS[entry['provider']]['torrents_url']
        assert entry['api_key'] == entry['provider']+'-synthetic-key-only'
        return {'data':[{'attributes':{'info_hash':'a'*40,'freeleech':25,'double_upload':True,
            'featured':False,'internal':True,'refundable':True,'created_at':created,'uploader':'someone else'}}]}
    trackers.read_json = Mock(side_effect=search)
    found = trackers.benefits.lookup(('a'*40,), 'Release', trackers.entries())
    assert trackers.read_json.call_count == 2
    matches = {m['tracker_provider']:m for m in trackers.benefits.with_global(found,now=now)['matches']}
    assert matches['sagmire']['freeleech'] == 100
    assert matches['nordicbytes']['freeleech'] == 25
    assert all(m['double_upload'] and m['internal'] and m['refundable'] for m in matches.values())
    policy = policy_from_result({'status':'matched','matches':[matches['sagmire']]})
    assert policy['until'] == pytest.approx(now-60+GREEN_SECONDS)
    assert policy['known'] and policy['has_date']


@pytest.mark.parametrize('provider', PROVIDERS)
def test_badge_feeds_require_matching_tracker_account(provider, tmp_path):
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    client, headers = login(app)
    trackers = app.extensions['trackers']
    ident = trackers.save({'provider':provider,'name':provider,'api_key':KEY})
    trackers.cache[ident] = {'status':'ok','updated_at':time.time()}
    assert trackers.badge_ready(ident)
    own_host = PROVIDERS[provider]['hosts'][0]
    other_host = 'sagmire.org' if provider == 'nordicbytes' else 'nordicbytes.org'
    feed = {'name':'Provider feed','url':'https://'+own_host+'/rss?key=synthetic',
        'enabled':True,'ratio_limit':1,'ratio_action':'keep','required_badges':['freeleech'],'tracker_id':ident}
    assert client.post('/api/rss', headers=headers, json=feed).status_code == 200
    assert client.post('/api/rss', headers=headers, json={**feed,'url':'https://'+other_host+'/rss'}).status_code == 400
    # Editing an account must not silently approve its old provider's feed.
    other_provider = 'sagmire' if provider == 'nordicbytes' else 'nordicbytes'
    trackers.save({'id':ident,'provider':other_provider,'name':'Changed','api_key':KEY})
    trackers.cache[ident] = {'status':'ok','updated_at':time.time()}
    app.extensions['state'].save('c'*32, True)
    runtime = app.extensions['runtime']
    runtime.rpc.reset_mock()
    RssGate(app.extensions['rss'], runtime, app.extensions['state'], trackers.benefits).tick()
    runtime.rpc.assert_not_called()


def test_switching_provider_does_not_reuse_pending_benefit_cache(tmp_path):
    trackers = Trackers(tmp_path)
    data = {'provider':'nordicbytes','name':'Same name','api_key':KEY}
    ident = trackers.save(data)
    meta = {'hashes':['a'*40],'name':'Release'}
    trackers.benefits.request(meta)
    trackers.save({**data,'id':ident,'provider':'sagmire'})
    trackers.benefits.request(meta)
    assert trackers.benefits.jobs.qsize() == 2
    assert len(trackers.benefits.cache) == 2
    now = time.time()
    trackers.cache[ident] = {'status':'ok','updated_at':now,'events':[{'type':'global_freeleech',
        'ends_at':datetime.fromtimestamp(now+600,timezone.utc).isoformat()}]}
    old = {'status':'matched','matches':[{'tracker_id':ident,'tracker_provider':'nordicbytes','freeleech':25}]}
    match = trackers.benefits.with_global(old,now=now)['matches'][0]
    assert match['freeleech'] == 25 and not match.get('global_freeleech')
