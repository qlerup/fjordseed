"""Audio-only conversion retains track identity, layouts and copied video."""
from copy import deepcopy
import shutil
import subprocess

import pytest

from conversion_media import audio_command,audio_plan,command,probe,validate_audio,conversion_mode,checked_audio_selection,prepare_output
from media_bitrates import estimate_sizes
from test_conversion import media
from test_conversion_queue import prepare
from test_remote_conversion import setup


def original():
    data=media()
    data['streams'][1].update(channel_layout='7.1',sample_rate='48000',profile='TrueHD+Atmos')
    for channels,layout,language in [(6,'5.1(side)','dan'),(2,'stereo','deu')]:
        data['streams'].append({'codec_type':'audio','codec_name':'aac','channels':channels,
            'channel_layout':layout,'sample_rate':'48000','tags':{'language':language,'title':language}})
    return data


def converted(data):
    result=deepcopy(data)
    for stream,track in zip((s for s in result['streams'] if s['codec_type']=='audio'),audio_plan(data)):
        stream['codec_name']=track['output_codec']
    return result


def test_every_audio_track_is_mapped_and_object_audio_is_copied():
    data=original();plan=audio_plan(data)
    assert [t['language'] for t in plan]==['eng','dan','deu']
    assert [t['action'] for t in plan]==['copy','convert','convert']
    args=command('in.mkv','out.mkv',20,data,conversion_mode='audio')
    assert args==audio_command('in.mkv','out.mkv',data)
    assert args[0]=='ffmpeg' and args[args.index('-map')+1]=='0'
    assert '-c:a:0' not in args
    assert args[args.index('-c:a:1')+1]=='flac'
    assert not any(arg.startswith('-ac:') for arg in args)
    assert '-c:v' not in args and args[args.index('-c')+1]=='copy'


def test_unknown_mode_and_ambiguous_surround_fail_closed():
    with pytest.raises(ValueError):conversion_mode('stereo')
    data=original();data['streams'][-2].pop('channel_layout')
    with pytest.raises(ValueError,match='kanal'):audio_plan(data)


@pytest.mark.parametrize('change',['missing','channels','layout','language','profile','video','dovi'])
def test_result_validation_rejects_track_or_video_loss(change):
    data=original();result=converted(data)
    validate_audio(data,result)
    if change=='missing':result['streams'].pop()
    if change=='channels':result['streams'][-1]['channels']=1
    if change=='layout':result['streams'][-2]['channel_layout']='stereo'
    if change=='language':result['streams'][-1]['tags']['language']='fra'
    if change=='profile':result['streams'][1]['profile']='TrueHD'
    if change=='video':result['streams'][0]['codec_name']='h264'
    if change=='dovi':result['streams'][0]['side_data_list'].pop(0)
    with pytest.raises(ValueError):validate_audio(data,result)


def test_estimates_include_all_other_tracks_and_can_indicate_growth():
    result=estimate_sizes(7200,60_000_000,65_000_000,58_500_000_000)
    assert result['20']['estimated_bytes']==22_725_000_000
    assert result['30']['estimated_bytes']==31_815_000_000
    assert result['40']['estimated_bytes']==40_905_000_000
    assert result['audio']['estimated_bytes'] is None
    assert estimate_sizes(None,None,None,100)['20']['estimated_bytes'] is None
    assert estimate_sizes(100,1_000_000,2_000_000,25_000_000)['40']['saved_bytes']<0


def test_audio_mode_requires_new_client_and_survives_persisted_queue(setup,monkeypatch):
    manager,pc,jobs,add=prepare(setup,monkeypatch)
    with pytest.raises(ValueError,match='Opdatér'):manager.select_file(pc['id'],r'M:\Bibliotek','a.mkv',30,'audio')
    manager.workspace(pc,r'M:\Bibliotek',conversion_version=3)
    selected=manager.select_file(pc['id'],r'M:\Bibliotek','a.mkv',30,'audio')
    assert selected['conversion_mode']=='audio'
    assert manager.devices()[0]['queue'][0]['conversion_mode']=='audio'
    assert next(iter(jobs.values()))['conversion_mode']=='audio'


@pytest.mark.parametrize('layout,codec,channels,output_codec',[('7.1','aac',8,'flac'),('5.1(side)','ac3',6,'flac')])
@pytest.mark.parametrize('selection',[None,[0],[1]])
def test_real_multilingual_surround_and_stereo_remux_preserves_video(tmp_path,layout,codec,channels,output_codec,selection):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('ffmpeg/ffprobe required')
    source=tmp_path/'source.mkv';target=tmp_path/'target.mkv'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=s=64x64:r=24:d=1',
        '-f','lavfi','-i',f'anullsrc=cl={layout}:r=48000','-f','lavfi','-i','anullsrc=cl=stereo:r=48000',
        '-map','0:v','-map','1:a','-map','2:a','-c:v','ffv1','-c:a:0',codec,'-c:a:1','aac',
        '-metadata:s:a:0','language=dan','-metadata:s:a:0','title=Dansk surround',
        '-metadata:s:a:1','language=eng','-metadata:s:a:1','title=English commentary','-t','1',str(source)],check=True,capture_output=True)
    before=probe(source)
    from media_bitrates import probe as scan
    assert [(t['index'],t['description']) for t in scan(source)['audio_tracks']]==[(0,'Dansk surround'),(1,'English commentary')]
    subprocess.run(audio_command(source,target,before,selection),check=True,capture_output=True)
    after=probe(target);validate_audio(before,after,selection)
    tracks=[s for s in after['streams'] if s['codec_type']=='audio']
    expected=[(output_codec,channels,layout,'dan','Dansk surround'),('flac',2,'stereo','eng','English commentary')]
    assert [(s['codec_name'],s['channels'],s['channel_layout'],s['tags']['language'],s['tags']['title']) for s in tracks]==[track for index,track in enumerate(expected) if selection is None or index in selection]
    def video_hash(path):
        return subprocess.run(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0','-c','copy','-f','hash','-hash','sha256','-'],check=True,capture_output=True).stdout
    assert video_hash(source)==video_hash(target)


@pytest.mark.parametrize('value',[[],[0,0],[-1],[True],[1.5],['0'],{},list(range(129))])
def test_invalid_track_selections_fail_before_start(value):
    with pytest.raises(ValueError):checked_audio_selection(value)


def test_selection_validates_bounds_and_ignores_deselected_unsupported_track():
    data=original();data['streams'][-2].pop('channel_layout')
    assert audio_plan(data,[2])[0]['index']==2
    with pytest.raises(ValueError,match='findes'):audio_plan(data,[5])
    args=audio_command('in.mkv','out.mkv',data,[2])
    assert '0:a:2' in args and '0:a:0' not in args
    assert checked_audio_selection([2,0])==[0,2]


def test_selected_tracks_are_used_for_flag_restoration(monkeypatch):
    import conversion_media as policy
    from unittest.mock import Mock
    data=original();selected=converted(data)
    selected['streams']=[s for s in selected['streams'] if s.get('codec_type')!='audio']+[selected['streams'][-1]]
    flags=Mock();monkeypatch.setattr(policy,'restore_flags',flags)
    monkeypatch.setattr(policy,'probe',Mock(return_value=selected))
    result=prepare_output(data,'out.mkv',conversion_mode='audio',selected_audio_tracks=[2])
    assert result is selected
    assert [s['tags']['language'] for s in flags.call_args.args[0]['streams'] if s['codec_type']=='audio']==['deu']
    with pytest.raises(ValueError):validate_audio(data,result)  # missing default-all tracks


def test_header_scan_returns_descriptions_and_stable_audio_indices(tmp_path,monkeypatch):
    from unittest.mock import Mock
    import media_bitrates as metadata
    import json
    path=tmp_path/'source.mkv';path.write_bytes(b'media')
    data=original()
    data['streams'][-1]['tags']['title']='English commentary (Director)'
    data['streams'][-2]['tags'].pop('title')
    data['streams'][-2]['tags']['DESCRIPTION']='Dansk original lyd'
    data['streams'][-2]['index']=5
    monkeypatch.setattr(metadata.subprocess,'run',Mock(return_value=Mock(stdout=json.dumps(data))))
    result=metadata.probe(path)
    assert [(t['index'],t['description']) for t in result['audio_tracks']]==[(0,''),(1,'Dansk original lyd'),(2,'English commentary (Director)')]
    assert result['audio_tracks'][1]['stream_index']==5


@pytest.mark.parametrize('selection',[[0],[1,0]])
def test_selected_indices_survive_persisted_queue(setup,monkeypatch,selection):
    manager,pc,jobs,add=prepare(setup,monkeypatch)
    manager.workspace(pc,r'M:\Bibliotek',conversion_version=3)
    chosen=manager.select_file(pc['id'],r'M:\Bibliotek','a.mkv',30,'audio',selection)
    assert chosen['selected_audio_tracks']==sorted(selection)
    assert manager.devices()[0]['queue'][0]['selected_audio_tracks']==sorted(selection)
    assert next(iter(jobs.values()))['selected_audio_tracks']==sorted(selection)
