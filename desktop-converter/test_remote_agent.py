import importlib.util
import json
from pathlib import Path
import sys
import threading

import pytest

HERE=Path(__file__).parent
sys.path.insert(0,str(HERE))
from remote_agent import Agent,WorkerError


def agent(tmp_path):
    return Agent('https://seed.example.test','fsw_'+'a'*48,tmp_path,threading.Lock(),None,RuntimeError,lambda *a:None)


@pytest.mark.parametrize('url',['ftp://seed.test','https://name:password@seed.test','https://seed.test/?token=secret','https://seed.test/#token=secret'])
def test_pairing_url_cannot_embed_credentials_or_tokens(tmp_path,url):
    with pytest.raises(ValueError):Agent(url,'fsw_'+'a'*48,tmp_path,threading.Lock(),None,RuntimeError,lambda *a:None)


def test_chunk_retry_is_bounded_and_reuses_same_offset(tmp_path,monkeypatch):
    a=agent(tmp_path);calls=[]
    def call(*args,**kw):
        calls.append((args,kw))
        if len(calls)==1:raise WorkerError('Lost acknowledgement')
        return {'offset':4}
    a.call=call
    monkeypatch.setattr(a.stop,'wait',lambda *a:False)
    assert a.transfer('PUT','/jobs/a/files/0?offset=0',b'data',lease='lease')=={'offset':4}
    assert len(calls)==2 and calls[0]==calls[1]


def test_revoked_token_does_not_retry_or_log_secret(tmp_path):
    a=agent(tmp_path);calls=[]
    def call(*args,**kw):calls.append(1);raise WorkerError('HTTP 401',401)
    a.call=call
    with pytest.raises(WorkerError,match='401'):a.transfer('POST','/claim',{})
    assert len(calls)==1


@pytest.mark.skipif(sys.platform!='win32',reason='Windows DPAPI')
def test_pairing_token_is_encrypted_for_current_windows_user():
    from windows_secret import protect,unprotect
    token='fsw_'+'fixture'*8
    stored=protect(token)
    assert token not in stored and unprotect(stored)==token


@pytest.mark.parametrize('rates',[(20,40),(30,20),(40,30),(25,40)])
def test_received_job_automatically_selects_encoder_bitrate_and_ui(tmp_path,rates):
    from unittest.mock import Mock
    from remote_panel import RemotePanel
    from fjord_ui import QUALITY_CHOICES
    a=agent(tmp_path)
    a.renew=lambda finished:None
    panel=RemotePanel.__new__(RemotePanel)
    panel.quality=Mock()
    a.notify=lambda kind,value:panel.event(kind,value) if kind=='settings' else None
    actual=[]
    def convert(source,folder,rate,progress,stop):
        actual.append(rate)
        target=folder/'result.mkv'
        target.write_bytes(b'converted')
        return target
    a.convert=convert
    def transfer(method,path,data=None,**kwargs):
        if method=='GET':return b'original'
        if method=='PUT':return {'offset':len(data)}
        return {}
    a.transfer=transfer
    for index,rate in enumerate(rates):
        job={'id':str(index)*32,'lease':'b'*32,'bitrate':rate,
             'files':[{'index':0,'name':'film.mkv','size':8,'output':'film.mkv','video':True}]}
        a.run_job(job)
        assert actual[-1]==rate
        assert panel.quality.set.call_args.args[0]==QUALITY_CHOICES.get(rate,f'{rate} Mbps \u2013 tidligere valg')
        assert not (a.cache/job['id']).exists()
    assert actual==list(rates)


@pytest.mark.parametrize('rate',[None,True,'40',0,45])
def test_invalid_remote_bitrate_is_rejected_before_download(tmp_path,rate):
    a=agent(tmp_path)
    with pytest.raises(WorkerError,match='videobitrate'):
        a.run_job({'id':'a'*32,'bitrate':rate})
    assert not (a.cache/('a'*32)).exists()


def pairing_code(data):
    import base64
    return 'fsp1_'+base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip('=')


def test_pairing_code_supplies_address_and_raw_token_to_agent(tmp_path):
    from remote_agent import connection_details
    token='fsw_'+'a'*48
    code=pairing_code({'server':'http://192.168.1.110:8099','token':token})
    assert connection_details('',code)==('http://192.168.1.110:8099',token)
    a=Agent('',code,tmp_path,threading.Lock(),None,RuntimeError,lambda *a:None)
    assert a.server=='http://192.168.1.110:8099' and a.token==token
    assert connection_details('https://seed.test',token)==('https://seed.test',token)


@pytest.mark.parametrize('server',['ftp://seed.test','https://name:password@seed.test','https://seed.test/?key=x','https://seed.test/#secret','https://seed.test/path','https://seed.test:bad'])
def test_pairing_code_rejects_unsafe_addresses(server):
    from remote_agent import connection_details
    with pytest.raises(ValueError,match='ugyldig'):
        connection_details('',pairing_code({'server':server,'token':'fsw_'+'a'*48}))


@pytest.mark.parametrize('data',[{},[],{'server':None,'token':'fsw_a'},{'server':'https://seed.test','token':'fsw_a\r\nX: evil'}])
def test_malformed_pairing_payload_is_rejected_without_exposing_token(data):
    from remote_agent import connection_details
    code=pairing_code(data)
    with pytest.raises(ValueError,match='ugyldig') as exc:connection_details('',code)
    assert code not in str(exc.value) and 'evil' not in str(exc.value)


def test_pasting_code_fills_pc_address_without_connecting():
    from unittest.mock import Mock
    from remote_panel import RemotePanel
    panel=RemotePanel.__new__(RemotePanel)
    panel.token=Mock();panel.token.get.return_value=pairing_code({'server':'https://seed.test','token':'fsw_'+'a'*48})
    panel.url=Mock();panel.status=Mock()
    panel.pairing_changed()
    panel.url.set.assert_called_once_with('https://seed.test')
