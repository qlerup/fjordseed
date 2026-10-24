from copy import deepcopy
from tools.rss_history_migration import transfer


def test_transfer_preserves_data_rebinds_future_updates_and_is_idempotent():
    source={'credited_uploaded':42,'downloads':{'a':{'title':'Show.S01E01','added_at':1,'uploaded':100,'downloaded':200,'credited_uploaded':42}}}
    ledger={'a':{'rss_feed_id':'old','rss_credited_uploaded':42,'rss_traffic_sample':{'uploaded':100}},
        '_rss_upload':{'feeds':{'old':deepcopy(source),'new':{'credited_uploaded':8,'downloads':{}}}}}
    result=transfer(ledger,'new',['old'])
    assert result['credited_uploaded']==50
    assert result['downloads']==source['downloads']
    assert ledger['a']=={'rss_feed_id':'new','rss_credited_uploaded':42,'rss_traffic_sample':{'uploaded':100}}
    assert ledger['_rss_upload']['feeds']['old']==dict(source,migrated_to='new')
    before=deepcopy(ledger);transfer(ledger,'new',['old','old']);assert ledger==before


def test_next_live_sample_adds_only_new_traffic():
    from green_credit import CreditLedger
    old='a'*32;new='b'*32;ident='c'*40
    row={'hash':ident,'name':'Show.S01E01','uploaded':1000,'downloaded':500,'added_on':10,'tags':'FjordSeed-RSS-'+old}
    with CreditLedger().transaction() as ledger:
        ledger.update(row,now=20)
        transfer(ledger.entries,new,[old])
    with CreditLedger().transaction() as ledger:
        ledger.update(dict(row,uploaded=1100,tags='FjordSeed-RSS-'+new),now=30)
        archive=ledger.entries['_rss_upload']['feeds'][new]
        assert archive['credited_uploaded']==1100
        assert archive['downloads'][ident]['uploaded']==1100
        assert archive['downloads'][ident]['downloaded']==500
