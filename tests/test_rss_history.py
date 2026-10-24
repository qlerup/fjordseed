import json

from app import create_app
from green_credit import CreditLedger
import green_credit as credit
from test_app import FakeRuntime, login


def test_titles_and_green_credit_survive_removal_restart_and_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(credit, 'CONFIG', tmp_path/'qbit')
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    client, headers = login(app)
    ident = client.post('/api/rss', headers=headers, json=dict(
        name='Film', url='https://tracker.example/rss', enabled=False,
        ratio_limit=2, ratio_action='delete')).json['id']
    row = dict(hash='a'*40, name='Film æøå <img src=x onerror=alert(1)>',
               tags='FjordSeed-RSS-'+ident, uploaded=1000, added_on=10)
    with CreditLedger().transaction() as ledger:
        ledger.register([row['hash']], 2, policy={'known':True, 'until':100})
        ledger.update(row, now=20)
        ledger.update(row, now=30)
        ledger.update({**row, 'uploaded':1400}, now=110)
        ledger.entries.pop(row['hash'])
    url = '/api/rss/'+ident+'/history'
    item = client.get(url).json['downloads'][0]
    assert item['title'] == row['name']
    assert item['credited_uploaded'] == 700
    # A later re-add accumulates credit without losing the earlier title history.
    with CreditLedger().transaction() as ledger:
        ledger.update({**row, 'uploaded':200, 'added_on':200}, now=210)
        ledger.update({**row, 'uploaded':50, 'added_on':200}, now=220)
        ledger.entries.pop(row['hash'])
    restarted = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    client, _ = login(restarted)
    items = client.get(url).json['downloads']
    assert len(items) == 1 and items[0]['credited_uploaded'] == 900
    assert client.get('/api/rss').json['feeds'][0]['credited_uploaded'] == 900
    assert 'tracker.example' not in json.dumps(items)
    assert restarted.test_client().get(url).status_code == 401
    assert client.get('/api/rss/not-a-feed/history').status_code == 404


def test_upgrade_archives_existing_full_credit_without_double_counting(tmp_path, monkeypatch):
    monkeypatch.setattr(credit, 'CONFIG', tmp_path/'qbit')
    row = dict(hash='a'*40, name='Existing film', uploaded=800, tags='FjordSeed-RSS-'+'b'*32)
    with CreditLedger().transaction() as ledger:
        ledger.update(row, now=10)
        del ledger.entries['_rss_upload']['feeds']['b'*32]['downloads']
        del ledger.entries['a'*40]['rss_title_recorded']
    with CreditLedger().transaction() as ledger:
        ledger.update(row, now=20)
        total = ledger.entries['_rss_upload']['feeds']['b'*32]
        assert total['credited_uploaded'] == 800
        assert total['downloads']['a'*40]['credited_uploaded'] == 800


def test_history_empty_and_read_error(tmp_path):
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    client, headers = login(app)
    ident = client.post('/api/rss', headers=headers, json=dict(
        name='Film', url='https://tracker.example/rss', enabled=False, ratio_limit=1)).json['id']
    assert client.get('/api/rss/'+ident+'/history').json == {'downloads':[]}
    (tmp_path/'qbit').mkdir(exist_ok=True)
    (tmp_path/'qbit/green-credit.json').write_text('{broken')
    assert client.get('/api/rss/'+ident+'/history').status_code == 503
