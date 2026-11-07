import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from subtitle_progress import telemetry, present, summary
from subtitle_translation import Translations
from subtitle_library_refresh import LibraryRefresh


def test_extraction_and_ocr_live_progress_is_attempt_scoped(tmp_path):
    ident='a'*32
    telemetry(tmp_path,ident,stage='extract',duration=100)
    (tmp_path/'subtitle-work'/(ident+'.ffmpeg')).write_text('out_time_us=50000000\nprogress=continue\n')
    job=dict(job='job',state='running',stage='extract',progress_id=ident,progress=0)
    assert present(job,tmp_path)['stage_progress']==.5
    assert present(job,tmp_path)['progress']==8
    telemetry(tmp_path,ident,stage='ocr',fraction=.5,cues=10)
    status=present(job,tmp_path)
    assert status['stage']=='ocr' and status['progress']==25
    assert '10 undertekster' in status['detail']
    assert present({**job,'progress_id':'b'*32},tmp_path)['progress']==0
    assert present({**job,'state':'error'},tmp_path)['stage']=='extract'


def test_pgs_reports_progress_without_changing_cues(tmp_path):
    from test_subtitle_translation import pgs_fixture
    from subtitle_pgs import read_pgs
    path=tmp_path/'source.sup';path.write_bytes(pgs_fixture())
    updates=[]
    expected=read_pgs(path,'en',lambda *_:'Hello')
    actual=read_pgs(path,'en',lambda *_:'Hello',progress=lambda fraction,count:updates.append((fraction,count)))
    assert actual==expected
    assert updates[-1]==(1,len(expected))
    assert all(0<=fraction<=1 for fraction,_ in updates)


def test_overall_does_not_include_historical_completed_batches():
    jobs=[dict(job='old',batch='old',state='done',progress=100,created_at=1),
          dict(job='one',batch='new',state='done',progress=100,created_at=2),
          dict(job='two',batch='new',state='running',progress=50,created_at=3)]
    assert summary(jobs)==dict(total=2,done=1,errors=0,cancelled=0,running=1,progress=75)


def test_refresh_failure_keeps_srt_and_retries_without_translation(tmp_path,monkeypatch):
    def rpc(action,data):
        if action.endswith('validate'):return dict(id='film',title='Film',snapshot='stamp',fingerprint=['5','1'])
        if action.endswith('extract'):return dict(forced=False,cues=[dict(id=1,text='Hello',timing='00:00:01,000 --> 00:00:02,000')])
        if action.endswith('publish'):return dict(name='Film.da.srt',relative='Film.mkv')
    manager=Translations(SimpleNamespace(root=tmp_path),SimpleNamespace(rpc=rpc))
    monkeypatch.setattr(manager.auth,'models',lambda *_:[dict(id='model')])
    translate=Mock(side_effect=lambda *args:[dict(args[-1][0],text='Hej')])
    monkeypatch.setattr(manager.auth,'translate',translate)
    refresh=Mock(side_effect=[ValueError('Plex unavailable'),{'plex':'Klar','fjordflix':'Klar'}])
    monkeypatch.setattr(manager.library_refresh,'refresh',refresh)
    manager.enqueue('alice',dict(account='account',model='model',items=[dict(id='film',source='s',targets=['da'])]))
    manager.run_once()
    job=manager.listing('alice')[0]
    assert job['state']=='error' and job['progress']==95 and job['outputs']==['Film.da.srt']
    assert manager.summary('bob')['total']==0
    manager.change('alice',job['job'],'retry');manager.run_once()
    assert manager.listing('alice')[0]['progress']==100
    assert manager.listing('alice')[0]['refresh']['plex']=='Klar'
    assert translate.call_count==1


def test_refresh_targets_exact_plex_path(tmp_path,monkeypatch):
    import docker
    import subtitle_library_refresh as module
    (tmp_path/'subtitle-library.json').write_text(json.dumps(dict(fjordflix_root='/media',fjordflix_container='fjordflix',
        plex_root='/srv/media',plex_url='http://plex:32400',plex_token='secret')))
    client=Mock();client.containers.get.return_value.exec_run.return_value=SimpleNamespace(exit_code=0,output=b'["Film.da.srt"]')
    monkeypatch.setattr(docker,'from_env',lambda **_:client)
    session=Mock();session.headers={};session.__enter__=Mock(return_value=session);session.__exit__=Mock(return_value=False)
    def response(content):return SimpleNamespace(content=content.encode(),raise_for_status=lambda:None)
    session.get.side_effect=[response('<MediaContainer><Directory key="1" type="movie"><Location path="/srv/media"/></Directory></MediaContainer>'),
        response('<MediaContainer><Video ratingKey="9"><Media><Part file="/wrong/Film.mkv"/></Media></Video><Video ratingKey="10"><Media><Part file="/srv/media/Film.mkv"/></Media></Video></MediaContainer>'),
        response('<MediaContainer><Video><Media><Part file="/srv/media/Film.mkv"><Stream streamType="3" codec="srt" languageCode="dan" key="/library/streams/123"/></Part></Media></Video></MediaContainer>')]
    monkeypatch.setattr(module.requests,'Session',lambda:session)
    result=LibraryRefresh(tmp_path).refresh('Film.mkv',['Film.da.srt'],['da'])
    assert result['plex'].startswith('Klar')
    assert session.put.call_args.args[0]=='http://plex:32400/library/metadata/10/refresh'
    assert session.headers['X-Plex-Token']=='secret'


def test_invalid_refresh_paths_never_contact_services(tmp_path):
    for path in ('../Film.mkv','/Film.mkv'):
        with pytest.raises(ValueError):LibraryRefresh(tmp_path).refresh(path,[],[])


def test_plex_links_preserve_existing_files(tmp_path,monkeypatch):
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('plex_links',Path(__file__).parents[1]/'tools'/'plex_subtitle_links.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source=tmp_path/'source';source.mkdir();view=tmp_path/'view';view.mkdir()
    film=source/'Film.mkv';film.write_bytes(b'video')
    subtitle=source/'Film.da.srt';subtitle.write_text('subtitle')
    video=view/'Renamed.mkv'
    try:video.symlink_to(film)
    except OSError:pytest.skip('Symlink permission required')
    ledger=tmp_path/'links.json';ledger.write_text(json.dumps({'Renamed.mkv':str(film)}))
    monkeypatch.setattr(module,'SOURCE',source);monkeypatch.setattr(module,'VIEW',view);monkeypatch.setattr(module,'LEDGER',ledger)
    assert module.ensure_links('Film.mkv',['Film.da.srt'])==str(video)
    assert (view/'Renamed.da.srt').resolve()==subtitle
    assert module.ensure_links('Film.mkv',['Film.da.srt'])==str(video)
    conflict=view/'Renamed.sv.srt';conflict.write_text('Keep me')
    (source/'Film.sv.srt').write_text('New')
    with pytest.raises(ValueError):module.ensure_links('Film.mkv',['Film.sv.srt'])
    assert conflict.read_text()=='Keep me'
