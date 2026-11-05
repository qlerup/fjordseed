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

def test_file_change_fails_without_touching_original(film,prepared):
    workflow.enqueue(film[-1],{'items':[prepared]})
    (film[1]/'film.mp4').write_bytes(b'new movie')
    with CreditLedger().transaction() as credit:workflow.tick(film[-1],film[3],credit)
    assert workflow.read()['jobs'][0]['state']=='error'
    assert not library.ledger().exists()
    assert (film[1]/'film.mp4').read_bytes()==b'new movie'

@pytest.mark.parametrize('codec', ['ac3','eac3'])
@pytest.mark.parametrize('layout,channels', [('mono',1),('stereo',2),('5.1',6)])
def test_real_audio_remux_preserves_video_and_original_audio(tmp_path,codec,layout,channels):
    import shutil, subprocess, json
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('ffmpeg/ffprobe unavailable')
    source=tmp_path/'original.mkv';target=tmp_path/'converted.mkv'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=24',
        '-f','lavfi','-i','anullsrc=r=48000:cl='+layout,'-t','1','-c:v','libx264','-pix_fmt','yuv420p',
        '-c:a','flac','-metadata:s:a:0','language=dan',str(source)],check=True,timeout=30)
    def probe(path):return json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-show_chapters','-of','json',str(path)],capture_output=True,text=True,check=True).stdout)
    before=probe(source)
    selection=options.normalize({'mode':'audio','audio_codec':codec},before)
    subprocess.run(options.remux_command(source,None,target,before,selection),check=True,timeout=30)
    after=probe(target)
    audio=[s for s in after['streams'] if s['codec_type']=='audio']
    assert [s['codec_name'] for s in audio]==['flac',codec]
    assert all(s['channels']==channels and s['tags']['language']=='dan' for s in audio)
    options.validate_audio_only(options.reference(before,selection),after)
    def digest(path,stream):
        return subprocess.run(['ffmpeg','-v','error','-i',str(path),'-map',stream,'-c','copy','-f','hash','-'],capture_output=True,check=True).stdout
    assert digest(source,'0:v:0')==digest(target,'0:v:0')
    assert digest(source,'0:a:0')==digest(target,'0:a:0')


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
    worker.run_job(work)
    status=json.loads((work/'status.json').read_text())
    assert status['state']=='ready',status
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
    assert result['fingerprint']==prepared['fingerprint']
    assert result['media']['streams'][0]['codec_name']=='hevc'
    api.assert_not_called()


def test_manual_discovery_and_fingerprint_scoped_skip(film):
    path = film[0]/'Manuelt tilføjet.mkv'
    path.write_bytes(b'manual movie')
    ident = library.key(path)
    item = next(i for i in workflow.listing(film[-1])['items'] if i['id'] == ident)
    assert item['source'] == 'manual' and item['reviewed_modes'] == []
    assert not item['eligible']  # No qBittorrent ownership to move this original.
    workflow.skip(film[-1], {'id':ident, 'mode':'audio', 'skip':True})
    item = next(i for i in workflow.listing(film[-1])['items'] if i['id'] == ident)
    assert item['skipped_modes'] == ['audio'] and item['reviewed_modes'] == ['audio']
    path.write_bytes(b'a replacement movie')
    item = next(i for i in workflow.listing(film[-1])['items'] if i['id'] == ident)
    assert item['skipped_modes'] == []


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
