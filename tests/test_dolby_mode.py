from copy import deepcopy
from unittest.mock import Mock
import json
import pytest
import conversion_media as c
import dolby_backup as b
from test_conversion import media,job,record
from test_dolby_backup import path
from test_remote_conversion import setup
from test_library_conversion import film


def fake_probe(path,run=None):
    data=media()
    if b'Dolby metadata' not in path.read_bytes():
        data['streams'][0]['side_data_list']=[s for s in data['streams'][0]['side_data_list'] if s['side_data_type']!='DOVI configuration record']
        data['_rpu_frames']=0
    return data


@pytest.mark.parametrize('mode',['separate','preserve'])
def test_finalization_preserves_audio_and_applies_selected_dolby_policy(path,monkeypatch,mode):
    monkeypatch.setattr(c,'probe',fake_probe)
    monkeypatch.setattr(c,'restore_flags',Mock())
    before=path.read_bytes()
    result=c.prepare_output(media(),path,mode=mode)
    assert bool(c.dovi(result))==(mode=='preserve')
    assert b.sidecar(path).exists()==(mode=='separate')
    assert b'unchanged TrueHD Atmos payload' in path.read_bytes()
    c.validate_file(media(),path,mode=mode)
    if mode=='separate':
        c.prepare_output(media(),path,mode='preserve')
        assert path.read_bytes()==before and not b.sidecar(path).exists()
    else:assert path.read_bytes()==before


def test_preserve_rejects_missing_dolby_vision(path,monkeypatch):
    monkeypatch.setattr(c,'probe',fake_probe)
    b.suspend(path,media()['streams'][0]['side_data_list'][0])
    with pytest.raises(ValueError,match='Dolby Vision'):c.validate_file(media(),path,mode='preserve')


@pytest.mark.parametrize('mode',['separate','preserve'])
def test_non_dolby_film_does_not_get_dolby_added(path,monkeypatch,mode):
    original=media();original['streams'][0]['side_data_list'].pop(0);original['_rpu_frames']=0
    monkeypatch.setattr(c,'probe',lambda *a,**kw:deepcopy(original))
    monkeypatch.setattr(c,'restore_flags',Mock())
    assert not c.dovi(c.prepare_output(original,path,mode=mode))
    assert not b.sidecar(path).exists()


@pytest.mark.parametrize('bad',['unknown',True,{},[]])
def test_invalid_mode_rejected_before_file_work(path,bad):
    with pytest.raises(ValueError):c.prepare_output(media(),path,mode=bad)


def test_setting_persists_publishes_and_rejects_invalid_values(setup):
    app,manager,client,headers=setup
    assert client.get('/api/conversion').json['conversion_dolby_vision']=='separate'
    for mode in ('preserve','separate'):
        response=client.post('/api/conversion',headers=headers,json={'conversion_target':'pc','conversion_dolby_vision':mode})
        assert response.status_code==200
        assert client.get('/api/conversion').json['conversion_dolby_vision']==mode
        settings=json.loads((app.extensions['state'].root/'rpc/download-settings.json').read_text())
        assert settings['conversion_dolby_vision']==mode
    for bad in ('bad',True,[],{}):
        assert client.post('/api/conversion',headers=headers,json={'conversion_target':'pc','conversion_dolby_vision':bad}).status_code==400
    assert client.get('/api/conversion').json['conversion_dolby_vision']=='separate'


def test_library_job_freezes_mode_and_passes_it_to_pc_and_server(film):
    import shared_library as s
    import download_storage as storage
    command=s.queue(film[-1],{'device':'pc','name':'Movie/film.mp4','size':(film[0]/'Movie/film.mp4').stat().st_size,
        'media_folder':r'M:\Bibliotek','bitrate':30,'dolby_vision_mode':'preserve'})
    assert command['dolby_vision_mode']=='preserve'
    settings=json.loads(storage.SETTINGS.read_text());settings['conversion_dolby_vision']='separate';storage.SETTINGS.write_text(json.dumps(settings))
    result=s.fallback(film[-1],command['id'],'pc')
    assert result['dolby_vision_mode']=='preserve'
    from pathlib import Path
    request=json.loads((Path(s.owned(command['id'],'pc')['stage'])/'.fjordseed-conversion/request.json').read_text())
    assert request['dolby_vision_mode']=='preserve'


def test_automatic_download_keeps_dolby_choice_after_global_setting_changes(job):
    import download_storage as storage
    import conversion
    from pathlib import Path
    root,stage,api,row=job
    settings=json.loads(storage.SETTINGS.read_text());settings['conversion_dolby_vision']='preserve';storage.SETTINGS.write_text(json.dumps(settings))
    ident='b'*40
    second=Path(storage.prepare([ident],name='Another movie',convert=True))
    (second/'film.mkv').write_bytes(b'original')
    settings['conversion_dolby_vision']='separate';storage.SETTINGS.write_text(json.dumps(settings))
    assert storage.publish_complete(api,[{**row,'hash':ident,'save_path':str(second)}])==[]
    request=json.loads((second/conversion.DIRECTORY/'request.json').read_text())
    assert request['dolby_vision_mode']=='preserve'


def test_manual_library_uses_saved_dolby_choice(film):
    import download_storage as storage
    import library_conversion as library
    from pathlib import Path
    settings=json.loads(storage.SETTINGS.read_text());settings['conversion_dolby_vision']='preserve';storage.SETTINGS.write_text(json.dumps(settings))
    item=library.inventory(film[-1])['items'][0]
    result=library.queue(film[-1],item['id'],30)
    assert result['dolby_vision_mode']=='preserve'
    task=storage.read(library.ledger(),{})[result['id']]
    request=json.loads((Path(task['stage'])/'.fjordseed-conversion/request.json').read_text())
    assert request['dolby_vision_mode']=='preserve'
