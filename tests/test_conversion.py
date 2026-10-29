import json
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
import conversion
import download_storage as storage
from qbit_rpc import finish_seeding
from converter_worker import command,validate

HASH='a'*40


@pytest.fixture
def job(tmp_path,monkeypatch):
    monkeypatch.setattr('conversion.bitrate_decisions',lambda files,stage,bitrate:[dict(f,convert=True,input_total_bps=100_000_000) for f in files])
    root=tmp_path/'downloads';root.mkdir()
    settings=tmp_path/'settings.json';settings.write_text(json.dumps({'conversion_enabled':True,'conversion_bitrate':20,'streaming_enabled':False}))
    monkeypatch.setattr(storage,'SETTINGS',settings)
    (root/'.incomplete').mkdir()
    (root/'.incomplete'/conversion.HEARTBEAT).write_text(json.dumps({'version':1,'at':time.time()}))
    stage=Path(storage.prepare([HASH],name='Movie',convert=True))
    (stage/'film.mkv').write_bytes(b'original')
    api=Mock(return_value=Mock(json=lambda:[{'name':'film.mkv','size':8,'priority':1}]))
    row={'hash':HASH,'save_path':str(stage),'progress':1,'state':'uploading','share_limit_action':'RemoveWithContent'}
    return root,stage,api,row


def record():return storage.read(storage.CONFIG/'download-storage.json',{})[HASH]


def ready(stage):
    r=record();work=stage/conversion.DIRECTORY
    result=work/'result';result.mkdir();(result/'film.mkv').write_bytes(b'converted')
    (result/'.fjordseed-converted.json').write_text(json.dumps({'id':r['conversion_id']}))
    (work/'status.json').write_text(json.dumps({'id':r['conversion_id'],'state':'ready'}))


def test_buffer_publish_original_unchanged_and_delete_only_after_both_requirements(job):
    root,stage,api,row=job
    assert stage.parent==root/'.incomplete'
    assert storage.publish_complete(api,[row])==[]
    assert (stage/conversion.DIRECTORY/'request.json').exists()
    assert not (root/'Movie').exists()
    credit={'ratio':1,'ratio_limit':1,'seeding_time':0}
    assert not finish_seeding(api,row,credit)
    assert not any(c.args[0]=='torrents/delete' for c in api.call_args_list)
    ready(stage)
    assert storage.publish_complete(api,[row])==[]
    assert (root/'Movie'/'film.mkv').read_bytes()==b'converted'
    assert (stage/'film.mkv').read_bytes()==b'original'
    assert not any(c.args[0]=='torrents/setLocation' for c in api.call_args_list)
    assert not finish_seeding(api,row,{**credit,'ratio':.9})
    assert finish_seeding(api,row,credit)
    assert api.call_args.args==('torrents/delete',{'hashes':HASH,'deleteFiles':'true'})


def test_time_limit_original_paused_and_output_placement_guard(job):
    root,stage,api,row=job
    storage.publish_complete(api,[row]);ready(stage);storage.publish_complete(api,[row])
    credit={'ratio':0,'ratio_limit':10,'seeding_time':49*3600,'stop_on_complete':True}
    assert finish_seeding(api,{**row,'state':'stoppedUP'},credit)
    api.reset_mock()
    assert not finish_seeding(api,{**row,'save_path':str(root/'Movie')},credit)
    api.assert_not_called()


def test_publish_recovers_crash_after_rename_but_never_overwrites(job):
    root,stage,api,row=job
    storage.publish_complete(api,[row]);ready(stage)
    (root/'Movie').mkdir();(root/'Movie'/'existing').write_text('keep')
    assert storage.publish_complete(api,[row])
    assert (root/'Movie'/'existing').read_text()=='keep'
    (root/'Movie'/'existing').unlink();(root/'Movie').rmdir()
    (stage/conversion.DIRECTORY/'result').rename(root/'Movie')
    assert storage.publish_complete(api,[row])==[]
    assert record()['published']


def test_master_off_blocks_new_jobs_but_keeps_captured_job(job):
    root,stage,api,row=job
    storage.SETTINGS.write_text(json.dumps({'conversion_enabled':False}))
    with pytest.raises(ValueError):storage.prepare(['b'*40],name='Other',convert=True)
    assert storage.publish_complete(api,[row])==[]
    assert record()['conversion_bitrate']==20


@pytest.mark.parametrize('name',['../film.mkv','/film.mkv','foo\\film.mkv','.fjordseed-conversion/request.json','a/../../b'])
def test_rejects_paths(name):
    with pytest.raises(ValueError):conversion.safe_relative(name)


def test_missing_selected_files_does_not_queue_or_delete(job):
    root,stage,api,row=job
    (stage/'film.mkv').unlink()
    assert storage.publish_complete(api,[row])
    assert not (stage/conversion.DIRECTORY/'request.json').exists()
    assert not finish_seeding(api,row,{'ratio':100,'ratio_limit':1})


def media():
    return {'format':{'duration':'900'},'_rpu_frames':3,'chapters':[], 'streams':[
        {'codec_type':'video','codec_name':'hevc','width':3840,'height':2160,'pix_fmt':'yuv420p10le',
         'avg_frame_rate':'24000/1001','color_transfer':'smpte2084','side_data_list':[
             {'side_data_type':'DOVI configuration record','dv_profile':8,'dv_bl_signal_compatibility_id':1,'dv_level':6,
              'bl_present_flag':1,'el_present_flag':0,'rpu_present_flag':1},
             {'side_data_type':'Mastering display metadata'}]},
        {'codec_type':'audio','codec_name':'truehd','channels':8,'tags':{'language':'eng'}},
        {'codec_type':'subtitle','codec_name':'subrip','tags':{'language':'dan'}}]}


def test_gpu_preserves_tracks_and_rejects_missing_dovi():
    original=media();args=command(Path('in.mkv'),Path('out.mkv'),20,original)
    assert args[0]=='nvencc' and '--dolby-vision-rpu' in args and '--audio-copy' in args
    assert '--seek' not in args and '--seekto' not in args and '--trim' not in args
    assert validate(original,media()) is None
    result=media();result['_rpu_frames']=0
    with pytest.raises(ValueError,match='Dolby Vision'):validate(original,result)
    result=media();result['streams'].pop()
    with pytest.raises(ValueError,match='subtitle'):validate(original,result)


def test_unsupported_dovi_fails_without_losing_original():
    data=media();data['streams'][0]['side_data_list'][0]['dv_profile']=5
    with pytest.raises(ValueError,match='Dolby Vision'):command('in','out',20,data)


@pytest.mark.parametrize('rate',[20,30,40])
def test_quality_choice_reaches_encoder_with_variable_bitrate(rate):
    args=command(Path('in.mkv'),Path('out.mkv'),rate,media())
    assert args[args.index('--vbr')+1]==str(rate*1000)
    assert args[args.index('--max-bitrate')+1]==str(rate*1500)
    assert args[args.index('--output-depth')+1]=='10'


@pytest.mark.parametrize('profile',[7,8])
@pytest.mark.parametrize('reader',['avsw','avhw'])
def test_dolby_vision_preserves_source_level_instead_of_forcing_level_10(profile,reader):
    original=media();original['streams'][0]['side_data_list'][0]['dv_profile']=profile
    args=command('in.mkv','out.mkv',30,original,reader=reader)
    assert args[1]=='--'+reader
    assert args[args.index('--dolby-vision-profile')+1]=='copy'
    assert args[args.index('--dolby-vision-rpu')+1]=='copy'
    assert all(flag in args for flag in ['--repeat-headers','--aud','--pic-struct'])
    validate(original,media())


@pytest.mark.parametrize('field,value', [('dv_level',10),('dv_level',None),('el_present_flag',1),('bl_present_flag',0),('rpu_present_flag',0)])
def test_dolby_vision_rejects_changed_level_or_inconsistent_layers(field,value):
    original=media();result=media()
    result['streams'][0]['side_data_list'][0][field]=value
    with pytest.raises(ValueError,match='Dolby Vision'):
        validate(original,result)
