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
