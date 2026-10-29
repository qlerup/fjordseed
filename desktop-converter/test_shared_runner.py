import json
from pathlib import Path
import queue
import threading
from unittest.mock import Mock

from shared_runner import SharedRunner,work_paths,source_signature


class Cancelled(Exception):pass


def fixture(tmp_path):
    source=tmp_path/'film.mkv';source.write_bytes(b'original')
    command={'id':'a'*32,'attempt':'b'*32,'media_folder':str(tmp_path),'name':'film.mkv',
        'size':8,'bitrate':30,'work':'.fjordseed-shared/'+'a'*32+'/.fjordseed-conversion',
        'output':'film.mkv','action':'convert','state':'queued','phase':'queued'}
    command['source_signature']=source_signature(source)
    work=tmp_path/command['work'];(work/'result').mkdir(parents=True)
    prefs=tmp_path/'preferences.json';prefs.write_text(json.dumps({'media_folder':str(tmp_path)}))
    return source,command,work,prefs


def test_runner_encodes_on_share_then_sends_only_completion_metadata(tmp_path):
    source,command,work,prefs=fixture(tmp_path)
    def convert(input,folder,bitrate,notify,stop,target_name=None):
        assert input==source and folder.is_relative_to(tmp_path/'.fjordseed-shared') and bitrate==30
        (folder/target_name).write_bytes(b'converted')
        (folder/target_name).with_suffix('.json').write_text(json.dumps({'verified':True,'video_mbps_target':30}))
        notify('progress',(75,40,2))
    messages=queue.SimpleQueue()
    runner=SharedRunner(tmp_path/'connection.json',prefs,convert,Cancelled,messages,threading.Event())
    runner.request=Mock(side_effect=[command,{**command,'state':'completed'}])
    runner.run(command,str(tmp_path))
    assert source.read_bytes()==b'original'
    assert (work/'result'/'film.mkv').read_bytes()==b'converted'
    assert runner.request.call_args.args==(command,'POST','complete')
    events=[]
    while not messages.empty():events.append(messages.get_nowait()[0])
    assert 'job_progress' in events and 'job_done' in events


def test_changed_output_path_is_rejected(tmp_path):
    import pytest
    source,command,work,prefs=fixture(tmp_path)
    for data in ({'work':'../outside'},{'output':'../film.mkv'},{'output':'C:\\film.mkv'}):
        with pytest.raises(ValueError):work_paths({**command,**data},str(tmp_path))


def test_restart_after_server_move_never_reads_or_reencodes_old_source(tmp_path):
    source,command,work,prefs=fixture(tmp_path)
    source.unlink()
    convert=Mock(side_effect=AssertionError('must not encode twice'))
    runner=SharedRunner(tmp_path/'connection.json',prefs,convert,Cancelled,queue.SimpleQueue(),threading.Event())
    runner.request=Mock(return_value={**command,'state':'completed'})
    runner.run(command,str(tmp_path))
    convert.assert_not_called()


def test_cancel_stops_before_any_server_relocation(tmp_path):
    source,command,work,prefs=fixture(tmp_path)
    def convert(*args,**kwargs):raise Cancelled()
    runner=SharedRunner(tmp_path/'connection.json',prefs,convert,Cancelled,queue.SimpleQueue(),threading.Event())
    runner.request=Mock(side_effect=[command,{**command,'state':'cancelled'}])
    runner.run(command,str(tmp_path))
    assert source.read_bytes()==b'original'
    assert runner.request.call_args.args==(command,'POST','cancel')


def test_client_and_server_source_signature_protocol_agree(tmp_path):
    from shared_library import source_signature as server_signature
    source=tmp_path/'film.mkv';source.write_bytes(b'synthetic'*400000)
    assert source_signature(source)==server_signature(source)
    first=source_signature(source)
    with source.open('r+b') as handle:handle.seek(source.stat().st_size//2);handle.write(b'changed')
    assert source_signature(source)!=first


def test_move_error_reaches_ui_without_encoding_again(tmp_path):
    source,command,work,prefs=fixture(tmp_path)
    messages=queue.SimpleQueue();convert=Mock()
    runner=SharedRunner(tmp_path/'connection.json',prefs,convert,Cancelled,messages,threading.Event())
    runner.request=Mock(side_effect=[{**command,'state':'moving','phase':'moving'},
                                    {**command,'state':'error','detail':'Originalfilerne er ændret.'}])
    runner.stop.wait=Mock(return_value=False)
    runner.run(command,str(tmp_path))
    convert.assert_not_called()
    events=[]
    while not messages.empty():events.append(messages.get_nowait())
    assert ('job_error','Originalfilerne er ændret.') in events
    assert any(kind=='job_phase' for kind,_ in events)
