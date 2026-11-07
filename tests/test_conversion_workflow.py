from copy import deepcopy
from pathlib import Path
import pytest
import conversion_workflow as workflow
import conversion_options as options
import download_storage as storage
import library_conversion as library
from test_library_conversion import film, ready, move_by_qbit
from green_credit import CreditLedger
from conversion import DIRECTORY

@pytest.fixture
def media():
    return {'format': {'duration': '100'}, 'streams': [
        {'index':0,'codec_type':'video','codec_name':'hevc','width':3840,'height':2160},
        {'index':1,'codec_type':'audio','codec_name':'truehd','channels':6,'channel_layout':'5.1','bit_rate':'4000000','tags':{'language':'eng'},'disposition':{'default':1}},
        {'index':2,'codec_type':'audio','codec_name':'aac','channels':2,'bit_rate':'192000','tags':{'language':'dan'}},
        {'index':3,'codec_type':'subtitle','codec_name':'subrip','tags':{'language':'dan'}}]}

@pytest.fixture
def prepared(film, media, monkeypatch):
    monkeypatch.setattr(workflow, 'media_info', lambda _: deepcopy(media))
    path=film[1]/'film.mp4'
    return {'id':library.key(path), 'fingerprint':library.fingerprint(path),
            'options':{'mode':'full','bitrate':30,'audio_codec':'eac3','audio':[1],'subtitle':[3]},
            'policy':{'ratio_action':'delete_ratio','ratio_limit':2}}

def test_mode_boundaries_and_invalid_selections(media):
    video=options.normalize({'mode':'video','audio':[],'subtitle':[],'audio_codec':'ac3'},media)
    assert video['audio']==[1,2] and video['subtitle']==[3] and video['audio_codec']=='copy'
    audio=options.normalize({'mode':'audio','subtitle':[],'dolby_vision_mode':'separate'},media)
    assert audio['subtitle']==[3] and audio['dolby_vision_mode']=='preserve'
    for change in ({'audio':[99]}, {'audio':[True]}, {'audio':[1,1]}, {'bitrate':True}, {'audio_codec':'shell'}, {'mode':'other'}):
        with pytest.raises(ValueError):options.normalize({'mode':'full',**change},media)
    media['streams'][1]['channels']=8
    with pytest.raises(ValueError,match='5.1'):options.normalize({'mode':'full','audio_codec':'eac3'},media)
    assert options.normalize({'mode':'audio','audio_codec':'copy'},media)

def test_compatible_audio_keeps_original_tracks_channels_and_language(media):
    selected=options.normalize({'mode':'full','audio':[1],'subtitle':[],'audio_codec':'eac3'},media)
    ref=options.reference(media,selected)
    audio=[s for s in ref['streams'] if s['codec_type']=='audio']
    assert [s['codec_name'] for s in audio]==['truehd','eac3']
    assert all(s['channels']==6 and s['tags']['language']=='eng' for s in audio)
    assert audio[0]['disposition']['default']==1 and audio[1]['disposition']['default']==0
    command=options.remux_command('source.mkv','encoded.mkv','output.mkv',media,selected)
    assert command.count('0:1')==2 and '0:2' not in command and '0:3' not in command
    assert command[command.index('-c:a:1')+1]=='eac3' and '-ac' not in command
    assert '1:v:0' in command
    selected['mode']='audio'
    command=options.remux_command('source.mkv',None,'output.mkv',media,selected)
    assert '0:v:0' in command and '1:v:0' not in command

def test_estimates_are_mode_specific_and_missing_bitrate_is_unknown(media):
    selected=options.normalize({'mode':'full','audio_codec':'eac3'},media)
    assert options.estimate(media,1_000_000_000,selected)==round((30_000_000+4_192_000+832_000)*100/8*1.01)
    selected['mode']='audio'
    assert options.estimate(media,1_000_000_000,selected)>1_000_000_000
    del media['streams'][1]['bit_rate']
    assert options.estimate(media,1_000_000_000,selected) is None


def test_per_track_formats_independent_of_retained_originals(media):
    selected = options.normalize({'mode':'audio', 'audio':[],
                                  'audio_conversions':{'1':['ac3','eac3'], '2':['ac3']}}, media)
    assert options.normalize(selected, media) == selected
    audio = [s for s in options.reference(media, selected)['streams'] if s['codec_type']=='audio']
    assert [(s['codec_name'], s['tags']['language'], s['channels']) for s in audio] == [
        ('eac3','eng',6), ('ac3','eng',6), ('ac3','dan',2)]
    command = options.remux_command('in.mkv', None, 'out.mkv', media, selected)
    assert command.count('0:1') == 2 and command.count('0:2') == 1
    assert [command[command.index(f'-c:a:{i}')+1] for i in range(3)] == ['eac3','ac3','ac3']
    assert options.estimate(media, 1_000_000_000, selected) == 1_000_000_000 + (1_472_000-4_192_000)*100/8


def test_existing_eac3_all_languages_is_not_duplicated(media):
    source = media['streams'][1]
    source['codec_name'] = 'eac3'
    media['streams'] = [media['streams'][0]] + [
        {**deepcopy(source), 'index':i, 'tags':{'language':lang}}
        for i, lang in enumerate(('eng','dan','fin','nor','swe'), 1)]
    selected = options.normalize({'mode':'audio', 'audio_conversions':{
        str(i):['eac3','ac3'] for i in range(1,6)}}, media)
    audio = [s for s in options.reference(media, selected)['streams'] if s['codec_type']=='audio']
    assert [s['codec_name'] for s in audio] == ['eac3','ac3']*5
    assert [s['tags']['language'] for s in audio] == [lang for lang in ('eng','dan','fin','nor','swe') for _ in range(2)]
    assert all(c == ['ac3'] for c in selected['audio_conversions'].values())


@pytest.mark.parametrize('conversions', [[], {'99':['ac3']}, {'1':'ac3'}, {'1':['aac']}, {'1':['ac3','ac3']}, {'1':[{}]}])
def test_invalid_per_track_conversions(media, conversions):
    with pytest.raises(ValueError):
        options.normalize({'mode':'audio','audio_conversions':conversions},media)


def test_per_track_output_required_and_video_mode_keeps_originals(media):
    with pytest.raises(ValueError,match='mindst'):
        options.normalize({'mode':'audio','audio':[],'audio_conversions':{}},media)
    selected = options.normalize({'mode':'video','audio':[], 'audio_conversions':{'1':['ac3']}}, media)
    assert selected['audio']==[1,2] and selected['audio_conversions']=={}
    media['streams'][1]['channels']=8
    selected = options.normalize({'mode':'audio','audio_conversions':{'2':['ac3']}},media)
    assert selected['audio']==[1,2]  # Unsupported original does not block other languages.
    with pytest.raises(ValueError,match='5.1'):
        options.normalize({'mode':'audio','audio':[], 'audio_conversions':{'1':['ac3']}},media)

def test_batch_atomic_validation_skip_and_duplicate(film, prepared):
    api=film[-1]
    with pytest.raises(ValueError):workflow.enqueue(api,{'items':[prepared,{**prepared,'id':'absent'}]})
    assert not workflow.read()['jobs']
    workflow.skip(api,{'id':prepared['id'],'mode':'audio','skip':True})
    workflow.enqueue(api,{'items':[prepared]})
    assert workflow.pending(film[2]['hash']) and library.pending(film[2]['hash'])
    with pytest.raises(ValueError,match='allerede'):workflow.enqueue(api,{'items':[prepared]})
    assert workflow.listing(api)['items'][0]['skipped_modes']==['audio']
    assert not any(c.args[0]=='torrents/setLocation' for c in api.call_args_list)
    workflow.cancel(workflow.read()['jobs'][0]['id'])
    assert not workflow.pending(film[2]['hash'])

def test_queue_uses_server_then_pauses_before_native_move_and_applies_policy(film, prepared):
    root,current,row,rows,files,api=film
    workflow.enqueue(api,{'items':[prepared]})
    with CreditLedger().transaction() as credit:workflow.tick(api,rows,credit)
    job=next(iter(storage.read(library.ledger(),{}).values()))
    request=storage.read(Path(job['stage'])/DIRECTORY/'request.json',{})
    assert request['executor']=='server' and request['options']['audio']==[1]
    assert workflow.read()['jobs'][0]['state']=='running'
    ready(job)
    assert library.reconcile(api,rows)==[]
    calls=[c.args[0] for c in api.call_args_list]
    assert calls.index('torrents/stop')<calls.index('torrents/setLocation')
    move_by_qbit(film,job);row['state']='pausedUP'
    assert library.reconcile(api,rows)==[]
    assert (current/'film.mkv').read_bytes()==b'converted'
    with CreditLedger().transaction() as credit:
        workflow.tick(api,rows,credit)
        assert credit.entries[row['hash']]['target']==2
        assert credit.entries[row['hash']]['ratio_only'] is True
    assert workflow.read()['jobs'][0]['state']=='done'
    assert row['share_limit_action']=='RemoveWithContent'
    assert not workflow.pending(row['hash'])
    assert (Path(job['seed'])/'film.mp4').read_bytes()==b'original video'


def test_measured_worker_status_reaches_queue_and_eta_clears(film,prepared):
    from converter_worker import report
    workflow.enqueue(film[-1],{'items':[prepared]})
    workflow.tick(film[-1],film[3])
    job=next(iter(storage.read(library.ledger(),{}).values()))
    work=Path(job['stage'])/DIRECTORY
    report(work,job['id'],'encoding','Audio',25,stage='audio_encoding',eta_seconds=30)
    workflow.tick(film[-1],film[3])
    current=workflow.read()['jobs'][0]
    assert current['phase_progress']==25 and current['eta_seconds']==30 and current['stage']=='audio_encoding'
    report(work,job['id'],'verifying','Checking')
    workflow.tick(film[-1],film[3])
    current=workflow.read()['jobs'][0]
    assert current['phase_progress'] is None and current['eta_seconds'] is None

def test_file_change_fails_without_touching_original(film,prepared):
    workflow.enqueue(film[-1],{'items':[prepared]})
    (film[1]/'film.mp4').write_bytes(b'new movie')
    with CreditLedger().transaction() as credit:workflow.tick(film[-1],film[3],credit)
    assert workflow.read()['jobs'][0]['state']=='error'
    assert not library.ledger().exists()
    assert (film[1]/'film.mp4').read_bytes()==b'new movie'


def test_browser_fingerprint_preserves_nanoseconds_and_enqueues(film, prepared):
    import os
    source = film[1]/'film.mp4'
    timestamp = 1794015885417718001
    os.utime(source, ns=(timestamp, timestamp))
    stamp = library.fingerprint(source)
    details = workflow.details(film[-1], prepared['id'])
    assert details['fingerprint'] == [str(part) for part in stamp]
    assert all(type(part) is str for part in details['fingerprint'])
    item = next(i for i in workflow.listing(film[-1])['items'] if i['id']==prepared['id'])
    assert item['fingerprint'] == details['fingerprint']
    workflow.enqueue(film[-1], {'items':[{**prepared,'fingerprint':details['fingerprint']}]})
    assert workflow.read()['jobs'][0]['fingerprint'] == stamp


def test_fingerprint_does_not_hide_one_nanosecond_changes():
    stamp = [37473533952, 1794015885417718001]
    assert int(float(stamp[1])) != stamp[1]  # The old browser Number path loses precision.
    assert workflow.fingerprint_matches(workflow.browser_fingerprint(stamp), stamp)
    assert workflow.fingerprint_matches(stamp, stamp)  # Existing exact API callers.
    assert not workflow.fingerprint_matches([stamp[0], int(float(stamp[1]))], stamp)
    assert not workflow.fingerprint_matches(workflow.browser_fingerprint([stamp[0],stamp[1]+1]),stamp)
    for value in (None, [], {}, ['37473533952'], [True,stamp[1]], [stamp[0],float(stamp[1])]):
        assert not workflow.fingerprint_matches(value,stamp)


def test_changed_file_still_rejected_with_browser_fingerprint(film,prepared):
    stamp = workflow.browser_fingerprint(library.fingerprint(film[1]/'film.mp4'))
    (film[1]/'film.mp4').write_bytes(b'changed after opening the dialog')
    with pytest.raises(ValueError,match='Genåbn'):
        workflow.enqueue(film[-1],{'items':[{**prepared,'fingerprint':stamp}]})
    assert not workflow.read()['jobs']

@pytest.mark.parametrize('codec', ['ac3','eac3','both'])
@pytest.mark.parametrize('layout,channels', [('mono',1),('stereo',2),('5.1',6)])
@pytest.mark.parametrize('keep_original', [True, False])
def test_real_audio_remux_preserves_video_and_original_audio(tmp_path,codec,layout,channels,keep_original):
    import shutil, subprocess, json
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('ffmpeg/ffprobe unavailable')
    source=tmp_path/'original.mkv';target=tmp_path/'converted.mkv'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=24',
        '-f','lavfi','-i','anullsrc=r=48000:cl='+layout,'-t','1','-c:v','libx264','-pix_fmt','yuv420p',
        '-c:a','flac','-metadata:s:a:0','language=dan',str(source)],check=True,timeout=30)
    def probe(path):return json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-show_chapters','-of','json',str(path)],capture_output=True,text=True,check=True).stdout)
    before=probe(source)
    selection=options.normalize({'mode':'audio','audio_codec':codec},before)
    if not keep_original:
        selection=options.normalize({'mode':'audio','audio':[], 'audio_conversions':{
            str(s['index']):list(options.target_codecs(selection)) for s in before['streams'] if s['codec_type']=='audio'}},before)
    subprocess.run(options.remux_command(source,None,target,before,selection),check=True,timeout=30)
    after=probe(target)
    audio=[s for s in after['streams'] if s['codec_type']=='audio']
    targets = ['eac3','ac3'] if codec=='both' else [codec]
    assert [s['codec_name'] for s in audio]==(['flac'] if keep_original else [])+targets
    assert all(s['channels']==channels and s['tags']['language']=='dan' for s in audio)
    options.validate_audio_only(options.reference(before,selection),after)
    def digest(path,stream):
        return subprocess.run(['ffmpeg','-v','error','-i',str(path),'-map',stream,'-c','copy','-f','hash','-'],capture_output=True,check=True).stdout
    assert digest(source,'0:v:0')==digest(target,'0:v:0')
    if keep_original: assert digest(source,'0:a:0')==digest(target,'0:a:0')


def test_workflow_routes_require_login_and_csrf(tmp_path):
    from app import create_app
    from test_app import FakeRuntime,login
    app=create_app(tmp_path,testing=True,runtime_factory=FakeRuntime)
    client=app.test_client()
    assert client.get('/api/conversion/workflow').status_code==401
    assert client.post('/api/conversion/workflow/queue',json={}).status_code==403
    client,headers=login(app)
    assert client.post('/api/conversion/workflow/queue',json={}).status_code==403
    assert client.post('/api/conversion/workflow/queue',headers=headers,json=[]).status_code==400
    assert client.post('/api/conversion/workflow/delete',headers=headers,json={}).status_code==404
    assert client.post('/api/conversion/workflow/queue',headers=headers,json={'items':[]}).status_code==200
    app.extensions['runtime'].rpc.assert_called_once_with('library-workflow-queue',{'items':[]})


def test_restart_recovers_queued_library_job_without_duplicate(film,prepared):
    workflow.enqueue(film[-1],{'items':[prepared]})
    waiting=workflow.read()['jobs'][0]
    result=library.queue(film[-1],waiting['file_id'],30,options=waiting['options'],workflow_id=waiting['id'])
    with CreditLedger().transaction() as credit:workflow.tick(film[-1],film[3],credit)
    assert workflow.read()['jobs'][0]['library_id']==result['id']
    assert len(storage.read(library.ledger(),{}))==1


def test_same_torrent_second_movie_reuses_seeder_original(film,prepared):
    root,current,row,rows,files,api=film
    second=current/'second.mkv';second.write_bytes(b'another original video')
    files.append({'name':'second.mkv','size':second.stat().st_size,'priority':1})
    other={**prepared,'id':library.key(second),'fingerprint':library.fingerprint(second)}
    with pytest.raises(ValueError,match='samme seedingvalg'):
        workflow.enqueue(api,{'items':[prepared,{**other,'policy':{'ratio_action':'keep'}}]})
    workflow.enqueue(api,{'items':[prepared,other]})
    with CreditLedger().transaction() as credit:workflow.tick(api,rows,credit)
    first=next(iter(storage.read(library.ledger(),{}).values()))
    ready(first);assert library.reconcile(api,rows)==[]
    move_by_qbit(film,first);row['state']='pausedUP'
    assert library.reconcile(api,rows)==[]
    with CreditLedger().transaction() as credit:workflow.tick(api,rows,credit)
    with CreditLedger().transaction() as credit:workflow.tick(api,rows,credit)
    second_job=next(j for j in storage.read(library.ledger(),{}).values() if j['id']!=first['id'])
    assert second_job['reuse_seeding'] and second_job['seed']==first['seed']
    ready(second_job);assert library.reconcile(api,rows)==[]
    assert second.read_bytes()==b'converted'
    assert (Path(first['seed'])/'second.mkv').read_bytes()==b'another original video'
    assert (current/'film.mkv').read_bytes()==b'converted'
    assert len([c for c in api.call_args_list if c.args[0]=='torrents/setLocation'])==1


def test_preparation_releases_storage_lock_and_recovers_partial_copy(film,prepared,monkeypatch):
    import fcntl
    workflow.enqueue(film[-1],{'items':[prepared]})
    real_snapshot=library.snapshot
    attempts=[]
    def interrupted(source,target):
        # Separate open description: would fail if queue still held the lock.
        with (storage.CONFIG/'download-storage.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        attempts.append(target)
        target.write_bytes(b'partial')
        raise OSError('Simulated process interruption')
    monkeypatch.setattr(library,'snapshot',interrupted)
    workflow.tick(film[-1],film[3])
    assert workflow.read()['jobs'][0]['state']=='error'
    assert workflow.read()['jobs'][0].get('library_id')
    with pytest.raises(ValueError): workflow.cancel(workflow.read()['jobs'][0]['id'])
    assert (film[1]/'film.mp4').read_bytes()==b'original video'
    monkeypatch.setattr(library,'snapshot',real_snapshot)
    workflow.tick(film[-1],film[3])
    assert workflow.read()['jobs'][0]['state']=='running'
    jobs=storage.read(library.ledger(),{})
    assert len(jobs)==1
    job=next(iter(jobs.values()))
    assert job['phase']=='queued'
    assert (Path(job['stage'])/'film.mp4').read_bytes()==b'original video'


@pytest.mark.parametrize('mode',['full','video','audio'])
def test_worker_executes_reviewed_modes_and_publishes_receipt(tmp_path,monkeypatch,mode):
    import json,shutil,subprocess
    import converter_worker as worker
    import conversion_media
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('ffmpeg/ffprobe unavailable')
    source=tmp_path/'movie.mkv';work=tmp_path/DIRECTORY;work.mkdir()
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=24',
        '-f','lavfi','-i','anullsrc=r=48000:cl=5.1','-t','1','-c:v','libx264','-pix_fmt','yuv420p',
        '-c:a','flac','-metadata:s:a:0','language=dan',str(source)],check=True,timeout=30)
    selection={'mode':mode,'bitrate':30,'audio_codec':'eac3','dolby_vision_mode':'separate'}
    (work/'request.json').write_text(json.dumps({'version':1,'id':'a'*32,'executor':'server','bitrate':30,
        'options':selection,'files':[{'name':source.name,'size':source.stat().st_size}]}))
    # Exercise real audio/remux/probe/publication; substitute the unavailable GPU
    # only for video encoding, and mkvpropedit for this synthetic metadata case.
    video_calls=[]
    def encode(source,target,*args,**kwargs):
        video_calls.append(True)
        return ['ffmpeg','-v','error','-i',str(source),'-map','0','-c','copy',str(target)]
    monkeypatch.setattr(worker,'command',encode)
    monkeypatch.setattr(worker,'select_decoder',lambda *args:'avsw')
    monkeypatch.setattr(worker,'restore_flags',lambda *args,**kwargs:None)
    monkeypatch.setattr(conversion_media,'restore_flags',lambda *args,**kwargs:None)
    reports=[]
    real_report=worker.report
    def capture(*args,**kwargs):
        real_report(*args,**kwargs)
        reports.append(json.loads((work/'status.json').read_text()))
    monkeypatch.setattr(worker,'report',capture)
    worker.run_job(work)
    status=json.loads((work/'status.json').read_text())
    assert status['state']=='ready',status
    assert any(r['stage']=='audio_encoding' and r['progress']>0 for r in reports)
    assert len(video_calls)==(0 if mode=='audio' else 1)
    output=conversion_media.probe(work/'result'/'movie.mkv')
    audio=[s for s in output['streams'] if s['codec_type']=='audio']
    assert [s['codec_name'] for s in audio]==(['flac'] if mode=='video' else ['flac','eac3'])
    assert all(s['channels']==6 for s in audio)
    assert json.loads((work/'result'/'.fjordseed-converted.json').read_text())['files']==['movie.mkv']
    # Resume verifies the completed output rather than encoding it again.
    worker.run_job(work)
    assert json.loads((work/'status.json').read_text())['state']=='ready'
    assert len(video_calls)==(0 if mode=='audio' else 1)


def test_header_read_does_not_query_all_torrent_owners(film, prepared):
    api=film[-1];api.reset_mock()
    result=workflow.details(api,prepared['id'])
    assert result['fingerprint']==workflow.browser_fingerprint(prepared['fingerprint'])
    assert result['media']['streams'][0]['codec_name']=='hevc'
    api.assert_not_called()


def test_manual_discovery_and_fingerprint_scoped_skip(film):
    path = film[0]/'Manuelt tilføjet.mkv'
    path.write_bytes(b'manual movie')
    ident = library.key(path)
    item = next(i for i in workflow.listing(film[-1])['items'] if i['id'] == ident)
    assert item['source'] == 'manual' and item['reviewed_modes'] == []
    assert item['eligible']  # The file can be converted without moving its original.
    workflow.skip(film[-1], {'id':ident, 'mode':'audio', 'skip':True})
    item = next(i for i in workflow.listing(film[-1])['items'] if i['id'] == ident)
    assert item['skipped_modes'] == ['audio'] and item['reviewed_modes'] == ['audio']
    path.write_bytes(b'a replacement movie')
    item = next(i for i in workflow.listing(film[-1])['items'] if i['id'] == ident)
    assert item['skipped_modes'] == []


def manual_choice(film, media, monkeypatch):
    monkeypatch.setattr(workflow, 'media_info', lambda _: deepcopy(media))
    source = film[0]/'Manual.mkv'; source.write_bytes(b'manual original')
    return source, {'id':library.key(source),'fingerprint':library.fingerprint(source),
        'options':{'mode':'full','bitrate':20,'audio_codec':'copy'},'policy':{'ratio_action':'keep'}}


def prepare_manual(film, choice):
    workflow.enqueue(film[-1], {'items':[choice]})
    workflow.tick(film[-1], film[3])
    workflow.tick(film[-1], film[3])
    return next(j for j in storage.read(library.ledger(), {}).values() if j.get('manual'))


def test_manual_conversion_archives_original_beside_seeder_and_skips_seeding(film, media, monkeypatch):
    source, choice = manual_choice(film, media, monkeypatch)
    job = prepare_manual(film, choice)
    assert job['phase'] == 'queued'
    request = storage.read(Path(job['stage'])/DIRECTORY/'request.json', {})
    assert request['executor'] == 'server' and request['options']['mode'] == 'full'
    ready(job)
    assert library.reconcile(film[-1], film[3]) == []
    workflow.tick(film[-1], film[3])
    archive = Path(job['archive'])
    assert archive == storage.seeding_root().parent/'Originals'/'Manual.mkv'
    assert archive.read_bytes() == b'manual original' and not source.exists()
    target = Path(job['destination']); assert target.read_bytes() == b'converted'
    assert library.converted(target)['conversion_mode'] == 'full'
    assert workflow.read()['jobs'][0]['state'] == 'done'
    item = next(i for i in workflow.listing(film[-1])['items'] if i['id'] == library.key(target))
    assert set(item['completed_modes']) == {'audio','full','video'}
    assert not any(c.args[0] in ('torrents/setLocation','torrents/stop','torrents/start') for c in film[-1].call_args_list)
    assert library.reconcile(film[-1], film[3]) == []  # Restart cleanup retains both files.
    assert archive.exists() and target.exists()


def test_manual_delete_is_opt_in_and_only_after_successful_publication(film, media, monkeypatch):
    source, choice = manual_choice(film, media, monkeypatch)
    choice['options']['delete_original'] = True
    job = prepare_manual(film, choice)
    assert source.exists() and not Path(job['destination']).exists()
    ready(job); assert library.reconcile(film[-1], film[3]) == []
    assert not source.exists() and not Path(job['archive']).exists()
    target=Path(job['destination']); assert target.read_bytes()==b'converted'
    assert library.converted(target)['id'] == job['id']
    workflow.tick(film[-1], film[3])
    assert workflow.read()['jobs'][0]['state']=='done'
    assert 'slettet' in workflow.read()['jobs'][0]['detail']


@pytest.mark.parametrize('delete', [False,True])
def test_original_handling_recovers_a_crash_after_removing_source_path(film, media, monkeypatch, delete):
    source, choice = manual_choice(film, media, monkeypatch)
    choice['options']['delete_original']=delete
    job=prepare_manual(film, choice);ready(job)
    unlink=Path.unlink
    def interrupt(path, *args, **kwargs):
        result=unlink(path,*args,**kwargs)
        if path==source:raise SystemExit('simulated process interruption')
        return result
    monkeypatch.setattr(Path,'unlink',interrupt)
    with pytest.raises(SystemExit):library.reconcile(film[-1],film[3])
    monkeypatch.setattr(Path,'unlink',unlink)
    assert library.reconcile(film[-1],film[3])==[]
    saved=storage.read(library.ledger(),{})[job['id']]
    assert not saved['original_pending'] and not source.exists()
    assert Path(job['destination']).read_bytes()==b'converted'
    if not delete:assert Path(job['archive']).read_bytes()==b'manual original'


@pytest.mark.parametrize('changed', ['source','result'])
def test_deletion_rechecks_both_original_and_result_after_interruption(film, media, monkeypatch, changed):
    source, choice=manual_choice(film,media,monkeypatch);choice['options']['delete_original']=True
    job=prepare_manual(film,choice);ready(job)
    finish=library.finish_manual_original
    monkeypatch.setattr(library,'finish_manual_original',lambda *args:(_ for _ in ()).throw(OSError('interruption')))
    assert library.reconcile(film[-1],film[3])
    monkeypatch.setattr(library,'finish_manual_original',finish)
    path=source if changed=='source' else Path(job['destination']);path.write_bytes(b'new user content')
    assert library.reconcile(film[-1],film[3])
    assert source.exists()
    assert path.read_bytes()==b'new user content'


def test_originals_preserves_subfolders_and_does_not_overwrite_old_archives(film, media, monkeypatch):
    source, choice=manual_choice(film,media,monkeypatch)
    folder=source.parent/'Special';folder.mkdir();source=source.rename(folder/source.name)
    choice.update(id=library.key(source),fingerprint=library.fingerprint(source))
    archived=storage.originals_root()/'Special'/'Manual.mkv';archived.parent.mkdir();archived.write_bytes(b'old archive')
    job=prepare_manual(film,choice);ready(job)
    assert library.reconcile(film[-1],film[3])==[]
    assert Path(job['archive']).parent==archived.parent and Path(job['archive'])!=archived
    assert archived.read_bytes()==b'old archive'
    assert Path(job['archive']).read_bytes()==b'manual original'


def test_originals_is_not_listed_for_another_conversion(film, media, monkeypatch):
    monkeypatch.setattr(storage,'seeding_root',lambda:film[0]/'Seeder')
    source, choice=manual_choice(film,media,monkeypatch)
    job=prepare_manual(film,choice);ready(job)
    assert library.reconcile(film[-1],film[3])==[]
    assert not any(i['name'].startswith('Originals/') for i in workflow.listing(film[-1])['items'])


def test_cross_disk_original_archive_is_verified_outside_storage_lock(film, media, monkeypatch):
    import errno
    import shutil
    import os
    source, choice=manual_choice(film,media,monkeypatch)
    job=prepare_manual(film,choice);ready(job)
    archive=Path(job['archive']);link=os.link;copy=shutil.copy2;copied=[]
    def cross_disk(src,dst,*args,**kwargs):
        if Path(src)==source and Path(dst).parent==archive.parent:raise OSError(errno.EXDEV,'cross-device link')
        return link(src,dst,*args,**kwargs)
    def checked_copy(src,dst,*args,**kwargs):
        assert not storage._lock._is_owned()
        copied.append(Path(dst));return copy(src,dst,*args,**kwargs)
    monkeypatch.setattr(os,'link',cross_disk);monkeypatch.setattr(shutil,'copy2',checked_copy)
    assert library.reconcile(film[-1],film[3])==[]
    assert storage.read(library.ledger(),{})[job['id']]['archive_copy_required']
    assert library.reconcile(film[-1],film[3])==[]
    assert Path(job['stage']).is_dir() and source.exists()
    workflow.tick(film[-1],film[3]);assert copied and archive.read_bytes()==b'manual original'
    assert source.exists()  # A verified archive is required before the next publication pass.
    assert library.reconcile(film[-1],film[3])==[]
    workflow.tick(film[-1],film[3])
    assert not source.exists() and archive.exists()
    assert workflow.read()['jobs'][0]['state']=='done'


@pytest.mark.parametrize('corrupt', [False,True])
def test_cross_disk_result_must_match_before_original_can_be_deleted(film, media, monkeypatch, corrupt):
    import errno
    import os
    source,choice=manual_choice(film,media,monkeypatch);choice['options']['delete_original']=True
    job=prepare_manual(film,choice);ready(job)
    result=Path(job['stage'])/DIRECTORY/'result'/job['output'];link=os.link
    def cross_disk(src,dst,*args,**kwargs):
        if Path(src)==result:raise OSError(errno.EXDEV,'cross-device link')
        return link(src,dst,*args,**kwargs)
    monkeypatch.setattr(os,'link',cross_disk)
    assert library.reconcile(film[-1],film[3])==[]
    assert storage.read(library.ledger(),{})[job['id']]['result_verify_required']
    assert source.exists() and Path(job['stage']).exists()
    if corrupt:Path(job['destination']).write_bytes(b'bad copied result')
    workflow.tick(film[-1],film[3])
    if corrupt:
        assert workflow.read()['jobs'][0]['state']=='error' and source.exists()
    else:
        assert library.reconcile(film[-1],film[3])==[]
        assert not source.exists() and Path(job['destination']).read_bytes()==b'converted'


def test_new_torrent_ownership_prevents_original_deletion(film, media, monkeypatch):
    source, choice=manual_choice(film,media,monkeypatch);choice['options']['delete_original']=True
    job=prepare_manual(film,choice);ready(job)
    film[3].append({**film[2],'hash':'c'*40,'save_path':str(source.parent)})
    film[4].append({'name':source.name,'size':source.stat().st_size,'priority':1})
    assert library.reconcile(film[-1],film[3])
    assert source.read_bytes()==b'manual original'
    workflow.tick(film[-1],film[3])
    assert workflow.read()['jobs'][0]['state']=='error'


@pytest.mark.parametrize('value', ['true',1,None])
def test_original_deletion_choice_must_be_a_boolean(media,value):
    with pytest.raises(ValueError):options.normalize({'mode':'video','delete_original':value},media)


def test_torrent_original_deletion_cannot_bypass_seeding(film,prepared):
    with pytest.raises(ValueError,match='seeding'):
        workflow.enqueue(film[-1],{'items':[{**prepared,'options':{**prepared['options'],'delete_original':True}}]})


def test_new_torrent_before_start_requires_review_of_original_settings(film,media,monkeypatch):
    source,choice=manual_choice(film,media,monkeypatch);choice['options']['delete_original']=True
    workflow.enqueue(film[-1],{'items':[choice]})
    film[3].append({**film[2],'hash':'d'*40,'save_path':str(source.parent)})
    film[4].append({'name':source.name,'size':source.stat().st_size,'priority':1})
    workflow.tick(film[-1],film[3])
    assert workflow.read()['jobs'][0]['state']=='error'
    assert not storage.read(library.ledger(),{}) and source.exists()


@pytest.mark.parametrize('failure', ['changed_source','destination_exists','bad_receipt'])
def test_manual_publish_fails_without_overwriting_any_files(film, media, monkeypatch, failure):
    source, choice = manual_choice(film, media, monkeypatch)
    job = prepare_manual(film, choice); ready(job)
    target = Path(job['destination'])
    if failure == 'changed_source': source.write_bytes(b'new user file')
    if failure == 'destination_exists': target.write_bytes(b'existing user result')
    if failure == 'bad_receipt': (Path(job['stage'])/DIRECTORY/'result'/'.fjordseed-converted.json').write_text('{}')
    assert library.reconcile(film[-1], film[3])
    assert source.read_bytes() == (b'new user file' if failure == 'changed_source' else b'manual original')
    if failure == 'destination_exists': assert target.read_bytes() == b'existing user result'
    else: assert not target.exists()


def test_manual_files_reject_deletion_policy_and_existing_output_before_enqueue(film, media, monkeypatch):
    source, choice = manual_choice(film, media, monkeypatch)
    with pytest.raises(ValueError, match='originalfilen'):
        workflow.enqueue(film[-1], {'items':[{**choice,'policy':{'ratio_action':'delete_ratio','ratio_limit':2}}]})
    source.with_name('Manual.converted-full.mkv').write_bytes(b'existing')
    with pytest.raises(ValueError, match='allerede'):
        workflow.enqueue(film[-1], {'items':[choice]})
    assert not workflow.read()['jobs']


def test_batch_skip_validates_all_ids_before_changing_any_status(film):
    source=film[0]/'Manual.mkv';source.write_bytes(b'manual')
    ids=[library.key(source),library.key(film[1]/'film.mp4')]
    with pytest.raises(ValueError): workflow.skip(film[-1],{'ids':ids+['missing'],'mode':'video','skip':True})
    assert not workflow.read()['skipped']
    workflow.skip(film[-1], {'ids':ids,'mode':'video','skip':True})
    assert set(workflow.read()['skipped']['video']) == set(ids)
    assert 'audio' not in workflow.read()['skipped']


def test_ambiguous_torrent_ownership_still_allows_a_separate_conversion(film, media, monkeypatch):
    monkeypatch.setattr(workflow, 'media_info', lambda _: deepcopy(media))
    film[3].append({**film[2], 'hash':'b'*40})
    source=film[1]/'film.mp4'
    item=next(i for i in workflow.listing(film[-1])['items'] if i['id']==library.key(source))
    assert item['eligible'] and item['torrent_status']=='ambiguous'
    choice={'id':item['id'],'fingerprint':library.fingerprint(source),'options':{'mode':'video'},'policy':{'ratio_action':'keep'}}
    job=prepare_manual(film, choice)
    assert job['manual'] and Path(job['destination'])!=source


@pytest.mark.parametrize('mode,expected', [('full',['full','video','audio']),('video',['video']),('audio',['audio'])])
def test_persistent_conversion_tags_and_replaced_file(film, mode, expected):
    import json
    path=film[1]/'film.mp4'
    library.marker(path).write_text(json.dumps({'version':1, 'id':'test', 'output_size':path.stat().st_size,
        'output_fingerprint':library.fingerprint(path), 'conversion_mode':mode}))
    item=workflow.listing(film[-1])['items'][0]
    assert item['completed_modes'] == expected and item['source'] == 'converted'
    # A replacement of the same size must not inherit completed status.
    import os
    stat=path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns+1000000))
    assert workflow.listing(film[-1])['items'][0]['completed_modes'] == []


def test_legacy_conversion_tags_recover_mode_from_job():
    assert workflow.completed_modes({'id':'old'}, {'old':{'options':{'mode':'audio'}}}) == ['audio']
    assert workflow.completed_modes({'bitrate':30}, {}) == ['video']
