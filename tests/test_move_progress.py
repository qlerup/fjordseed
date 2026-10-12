from pathlib import Path
from types import SimpleNamespace
from download_storage import moving_progress


def test_move_estimate_uses_allocated_bytes_and_never_reports_complete(tmp_path,monkeypatch):
    target=tmp_path/'target';target.mkdir();payload=target/'movie.mkv';payload.write_bytes(b'x'*4096)
    original=Path.stat
    def stat(path,**kwargs):
        result=original(path,**kwargs)
        if path==payload and not kwargs:
            return SimpleNamespace(st_size=4096,st_blocks=4)
        return result
    monkeypatch.setattr(Path,'stat',stat)
    row={'hash':'a','state':'moving','size':4096,'share_limit_action':'Stop','save_path':'/old'}
    entries={'a':{'target':str(target),'stage':str(tmp_path/'stage')}}
    assert moving_progress(row,entries)['move_progress']==.5
    row['size']=1024
    assert moving_progress(row,entries)['move_progress']==.99
    row['share_limit_action']='RemoveWithContent'
    assert moving_progress(row,entries)['move_progress'] is None
    row['state']='stalledUP'
    assert moving_progress(row,entries)=={}


def test_unknown_move_does_not_use_download_completion():
    assert moving_progress({'hash':'a','state':'moving','progress':1}, {})=={'move_progress':None}
