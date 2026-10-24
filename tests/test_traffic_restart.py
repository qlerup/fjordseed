import json
from unittest.mock import Mock

import pytest
import green_credit
from green_credit import CreditLedger
from qbit_worker import sync_resume_interval

HASH='e'*40


def sample(uploaded,downloaded=1000,added=1,now=100):
    row={'hash':HASH,'uploaded':uploaded,'downloaded':downloaded,'added_on':added,
         'state':'stalledUP','ratio_limit':2,'ratio':uploaded/downloaded if downloaded else 0}
    with CreditLedger().transaction() as ledger:
        return ledger.update(row,now=now)


def test_old_checkpoint_does_not_erase_upload_or_count_restored_bytes_twice():
    assert sample(100)['uploaded']==100
    assert sample(1000,now=110)['uploaded']==1000
    reset=sample(400,now=120)
    assert reset['uploaded']==1000 and reset['client_uploaded']==400
    assert reset['ratio']==1 and reset['traffic_counter_rollback']
    assert sample(400,now=120)==reset
    assert sample(450,now=130)['uploaded']==1050
    assert sample(10,now=140)['uploaded']==1050
    assert sample(30,now=150)['uploaded']==1070


def test_download_history_also_survives_checkpoint_rollback():
    sample(100,downloaded=1000)
    reset=sample(100,downloaded=400,now=110)
    assert reset['downloaded']==1000 and reset['ratio']==.1
    assert sample(100,downloaded=450,now=120)['downloaded']==1050


def test_readding_a_torrent_starts_a_new_transfer_lifetime():
    sample(1000)
    new=sample(100,added=2,now=110)
    assert new['uploaded']==100 and new['ratio']==.1


def test_legacy_green_history_recovers_observed_bytes_after_restart():
    observed=11007712853;native=4199986567;downloaded=24328837981
    green_credit.POLICIES.write_text(json.dumps({'_enabled':True,HASH:{'known':True,'has_date':False,'until':None}}))
    with CreditLedger().transaction() as ledger:
        ledger.entries[HASH]={'target':2,'uploaded':native,'green_uploaded':0,'unclassified':observed,
            'at':100,'added_on':1,'policy':{'known':True,'has_date':False,'until':None},'classified':False,
            'adaptive_seeding':True,'upload_potential':{'basis':'physical-upload-v1','at':100,'since':0,
                'uploaded':native,'rate':100000000,'last_upload':100}}
    recovered=sample(native,downloaded=downloaded,now=110)
    assert recovered['uploaded']==observed
    assert recovered['ratio']==pytest.approx(observed/downloaded)
    assert recovered['credited_uploaded']==observed/2
    assert recovered['ratio_limit']==2 and not recovered['seeding_upload_potential']
    assert sample(native,downloaded=downloaded,now=120)['uploaded']==observed
    assert sample(native+100,downloaded=downloaded,now=130)['uploaded']==observed+100


@pytest.mark.parametrize('interval,update',[(60,True),(0,True),(1,False),(None,False)])
def test_resume_checkpoint_interval_is_one_minute_when_supported(interval,update):
    api=Mock();sync_resume_interval({'save_resume_data_interval':interval},api)
    assert api.called is update
    if update:assert json.loads(api.call_args.args[1]['json'])=={'save_resume_data_interval':1}
