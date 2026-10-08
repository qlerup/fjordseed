import io
import time

import pytest
from benefits import ratio_estimate
from torrent_meta import torrent_meta
from test_app import FakeRuntime,login
from app import create_app


@pytest.mark.parametrize('free,size,expected,warning',[
    (0,15,.5,True),(0,16,10/21,True),(0,14,10/19,False),
    (100,1000,2,False),(50,30,.5,True),(75,60,.5,True),(25,20,.5,True),
    (None,15,.5,True)])
def test_projected_ratio_and_inclusive_warning(free,size,expected,warning):
    result=ratio_estimate({'tracker_id':'a','tracker_name':'Demo','freeleech':free,'double_upload':True},
        {'status':'ok','updated_at':100,'stats':{'uploaded':10,'downloaded':5}},size,now=100)
    assert result['projected_ratio']==pytest.approx(expected)
    assert result['warning'] is warning
    assert result['assumed_no_freeleech'] is (free is None)


@pytest.mark.parametrize('account,size',[(None,100),
    ({'status':'error','updated_at':100,'stats':{'uploaded':10,'downloaded':5}},100),
    ({'status':'ok','updated_at':0,'stats':{'uploaded':10,'downloaded':5}},100),
    ({'status':'ok','updated_at':1000,'stats':{'uploaded':10,'downloaded':5}},100),
    ({'status':'ok','updated_at':100,'stats':{'uploaded':None,'downloaded':5}},100),
    ({'status':'ok','updated_at':100,'stats':{'uploaded':float('nan'),'downloaded':5}},100),
    ({'status':'ok','updated_at':100,'stats':{'uploaded':10,'downloaded':-1}},100),
    ({'status':'ok','updated_at':100,'stats':{'uploaded':10,'downloaded':5}},None)])
def test_missing_stale_or_invalid_values_never_show_false_safe_ratio(account,size):
    result=ratio_estimate({'freeleech':0},account,size,now=700)
    assert result['status']=='unknown' and result['warning'] is False
    assert 'projected_ratio' not in result


def test_zero_download_and_freeleech_no_division_by_zero():
    result=ratio_estimate({'freeleech':100},{'status':'ok','updated_at':100,
        'stats':{'uploaded':10,'downloaded':0}},100,now=100)
    assert result['infinite'] is True and result['projected_ratio'] is None
    assert result['charged_download']==0 and result['warning'] is False


def test_multifile_v2_size_and_invalid_lengths():
    assert torrent_meta(b'd4:infod4:name1:x5:filesld6:lengthi3eed6:lengthi7eeeee')['size']==10
    assert torrent_meta(b'd4:infod4:name1:x12:meta versioni2e9:file treed1:ad0:d6:lengthi3eee1:bd0:d6:lengthi7eeeeee')['size']==10
    assert torrent_meta(b'd4:infod4:name1:x6:lengthi-1eee')['size'] is None


def test_preview_uses_matching_account_file_size_and_is_read_only(tmp_path):
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    client,headers=login(app)
    trackers=app.extensions['trackers']
    ident=trackers.save({'provider':'nordicbytes','name':'Demo','api_key':'fixture-api-key-not-real'})
    trackers.cache[ident]={'status':'ok','updated_at':time.time(),'stats':{'uploaded':10,'downloaded':5}}
    trackers.benefits.request=lambda *args: {'status':'matched','matches':[
        {'tracker_id':ident,'tracker_name':'Demo','freeleech':0,'size':999}]}
    raw=b'd4:infod4:name1:x6:lengthi15eee'
    result=client.post('/api/torrents/preview',headers=headers,
        data={'torrent':(io.BytesIO(raw),'demo.torrent')}).json
    estimate=result['ratio_estimates'][0]
    assert estimate['torrent_size']==15 and estimate['projected_ratio']==.5 and estimate['warning'] is True
    app.extensions['runtime'].rpc.assert_not_called()
    result=client.post('/api/torrents/preview',headers=headers,
        data={'magnet':'magnet:?xt=urn:btih:'+'a'*40}).json
    assert result['ratio_estimates'][0]['torrent_size']==999
    trackers.benefits.request=lambda *args: {'status':'unknown','matches':[]}
    result=client.post('/api/torrents/preview',headers=headers,
        data={'tracker_id':ident,'torrent':(io.BytesIO(raw),'demo.torrent')}).json
    estimate=result['ratio_estimates'][0]
    assert estimate['warning'] is True and estimate['assumed_no_freeleech'] is True
    assert estimate['projected_ratio']==.5
