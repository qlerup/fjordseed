import json
import time
from pathlib import Path

import pytest
pytest.importorskip('fcntl')
import remote_helper as helper
from conversion import DIRECTORY


@pytest.fixture
def job(tmp_path,monkeypatch):
    buffer=tmp_path/'buffer';stage=buffer/'stage';work=stage/DIRECTORY;work.mkdir(parents=True)
    (stage/'film.mkv').write_bytes(b'original')
    request={'version':1,'id':'a'*32,'executor':'pc','bitrate':20,'files':[{'name':'film.mkv','size':8}]}
    (work/'request.json').write_text(json.dumps(request))
    monkeypatch.setattr(helper,'roots',lambda:[buffer])
    monkeypatch.setattr(helper,'probe',lambda p:{'file':str(p)})
    monkeypatch.setattr(helper,'restore_flags',lambda *a:None)
    monkeypatch.setattr('conversion_media.prepare_output',lambda *a:None)
    claim=helper.dispatch({'action':'claim','worker':'one'})
    data={'worker':'one','job':request['id'],'lease':claim['lease'],'index':0}
    return work,claim,data


def upload(work,data,payload=b'converted',offset=0):
    import hashlib
    args={**data,'part':'c'*32,'offset':offset,'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
    ready=helper.dispatch({**args,'action':'prepare_upload'})
    (Path(ready['directory'])/ready['name']).write_bytes(payload)
    return helper.dispatch({**args,'action':'append'})


def test_lease_excludes_other_workers_and_reclaims_after_expiry(job):
    work,claim,data=job
    assert helper.dispatch({'action':'claim','worker':'two'}) is None
    assert helper.dispatch({'action':'claim','worker':'one'})['lease']==claim['lease']
    lease=helper.read(helper.lease_path(work));lease['expires']=time.time()-1;helper.save_lease(work,lease)
    replacement=helper.dispatch({'action':'claim','worker':'two'})
    assert replacement['lease']!=claim['lease']
    with pytest.raises(ValueError):helper.dispatch({**data,'action':'read','offset':0,'size':8})


def test_chunks_are_scoped_idempotent_and_only_verified_results_publish(job):
    work,claim,data=job
    assert helper.dispatch({**data,'action':'read','offset':0,'size':4})==b'orig'
    for bad in ({'lease':'wrong'},{'index':8},{'offset':-1},{'size':helper.DOWNLOAD_CHUNK+1}):
        with pytest.raises(ValueError):helper.dispatch({**data,'action':'read','offset':0,'size':8,**bad})
    with pytest.raises(ValueError):helper.dispatch({**data,'action':'complete'})
    assert upload(work,data)['offset']==9
    assert upload(work,data)['offset']==9
    assert helper.dispatch({**data,'action':'verify','size':9})['verified']
    assert helper.dispatch({**data,'action':'complete'})['complete']
    helper.dispatch({**data,'action':'renew','phase':'encode','progress':80})
    assert helper.read(work/'status.json')['state']=='ready'
    assert helper.dispatch({**data,'action':'fail'})=={'failed':False}
    assert (work/'result'/'film.mkv').read_bytes()==b'converted'
    assert (work.parent/'film.mkv').read_bytes()==b'original'
    assert helper.dispatch({**data,'action':'complete'})['complete']
    with pytest.raises(ValueError):upload(work,data)


def test_server_validates_instead_of_trusting_pc_success(job,monkeypatch):
    work,claim,data=job;upload(work,data)
    def fail(*a):raise ValueError('HDR metadata missing')
    monkeypatch.setattr('conversion_media.prepare_output',fail)
    with pytest.raises(ValueError,match='HDR'):helper.dispatch({**data,'action':'verify','size':9})
    assert not (work/'result').exists()
    assert helper.read(helper.lease_path(work))['done']=={}
    assert (work.parent/'film.mkv').read_bytes()==b'original'


def test_symlinks_and_traversal_are_rejected(job):
    work,claim,data=job
    original=helper.read(work/'request.json')
    original['files'][0]['name']='../outside.mkv';(work/'request.json').write_text(json.dumps(original))
    with pytest.raises(ValueError):helper.dispatch({**data,'action':'read','offset':0,'size':8})
    original['files'][0]['name']='film.mkv';(work/'request.json').write_text(json.dumps(original))
    (work.parent/'film.mkv').unlink();(work.parent/'film.mkv').symlink_to('/etc/passwd')
    with pytest.raises(ValueError):helper.dispatch({**data,'action':'read','offset':0,'size':8})


@pytest.mark.parametrize('rate',[10,15,20,25,30,40])
def test_broker_keeps_quality_choice_including_legacy_jobs(job,rate):
    work,claim,data=job
    request=helper.read(work/'request.json')
    request['bitrate']=rate
    (work/'request.json').write_text(json.dumps(request))
    assert helper.manifest(work,request)


def test_claim_advertises_larger_uploads_and_read_accepts_bounded_batch(job):
    work,claim,data=job
    assert claim['upload_chunk_size']==32*1024**2
    assert helper.dispatch({**data,'action':'read','offset':0,'size':32*1024**2})==b'original'
    prepared=helper.dispatch({**data,'action':'prepare_upload','part':'d'*32,
        'offset':0,'size':9*1024**2,'sha256':'e'*64})
    assert prepared['name']=='d'*32
    with pytest.raises(ValueError):
        helper.dispatch({**data,'action':'prepare_upload','part':'d'*32,
            'offset':0,'size':32*1024**2+1,'sha256':'e'*64})
