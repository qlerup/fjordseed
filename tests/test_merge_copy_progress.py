import json
from pathlib import Path
import threading

from merge_copy_progress import measure, snapshot, progress_file
import merge_media as merge


def test_running_copy_reports_actual_bytes_and_eta_before_it_finishes(tmp_path):
    source=tmp_path/'source';source.write_bytes(b'x'*1000)
    target=tmp_path/'target';ready=threading.Event();finish=threading.Event();errors=[]
    ident='a'*32
    def copy():
        try:
            with measure(ident,source,target,'Kopierer resultatet'):
                with target.open('wb') as handle:
                    handle.write(b'x'*250);handle.flush();ready.set()
                    assert finish.wait(5)
                    handle.write(b'x'*750)
        except BaseException as exc:errors.append(exc)
    thread=threading.Thread(target=copy);thread.start()
    try:
        assert ready.wait(3)
        started=json.loads(progress_file(ident).read_text())['started_at']
        status=snapshot(ident,now=started+10)
        assert status['copied_bytes']==250 and status['total_bytes']==1000
        assert status['progress']==25 and status['eta_seconds']==30
        assert status['phase']=='copying' and thread.is_alive()
    finally:finish.set();thread.join(5)
    assert not errors and target.read_bytes()==source.read_bytes()
    assert snapshot(ident)=={}


def test_copy_step_replaces_old_remux_99_percent_and_hides_internal_paths(tmp_path):
    ident='b'*32;source=tmp_path/'source';source.write_bytes(b'x'*1000);target=tmp_path/'target'
    merge.save([{'id':ident,'owner':'alice','name':'Film','state':'running','phase':'copying','progress':None}])
    (merge.folder()/(ident+'.log')).write_text('#GUI#progress 100%')
    with measure(ident,source,target,'Kopierer resultatet til arbejdsmappen'):
        target.write_bytes(b'x'*400)
        row=merge.jobs_for('alice')['jobs'][0]
        assert row['progress']==40 and row['copied_bytes']==400
        assert 'target' not in row and str(tmp_path) not in json.dumps(row)
        target.write_bytes(source.read_bytes())
        assert snapshot(ident)['progress']==99  # Still flushing/checking, not completed.
        assert snapshot(ident)['eta_seconds'] is None
    row=merge.jobs_for('alice')['jobs'][0]
    assert row['progress'] is None and 'copied_bytes' not in row


def test_checking_tracks_does_not_reuse_the_finished_remux_progress():
    ident='c'*32
    merge.save([{'id':ident,'owner':'alice','state':'running','phase':'verifying','progress':None}])
    (merge.folder()/(ident+'.log')).write_text('#GUI#progress 100%')
    assert merge.jobs_for('alice')['jobs'][0]['progress'] is None


def test_library_publication_reports_its_cross_disk_copy(tmp_path,monkeypatch):
    import errno
    import os
    import library_conversion as library
    original_link=os.link;original_copy=library.shutil.copy2
    folder=tmp_path/'input';folder.mkdir();source=folder/'movie.mkv';source.write_bytes(b'x'*1000)
    destination=tmp_path/'library'/'movie.mkv';destination.parent.mkdir()
    ident='d'*32;job={'id':ident,'merge_id':ident}
    merge.save([{'id':ident,'owner':'alice','state':'running','phase':'finalizing','progress':None}])
    def cross_disk(source,target,*args,**kwargs):
        if Path(source).parent!=Path(target).parent: raise OSError(errno.EXDEV,'Cross-device link')
        return original_link(source,target,*args,**kwargs)
    observed=[]
    def copy(source,target,*args,**kwargs):
        Path(target).write_bytes(b'x'*500)
        observed.append(merge.jobs_for('alice')['jobs'][0])
        return original_copy(source,target,*args,**kwargs)
    monkeypatch.setattr(os,'link',cross_disk);monkeypatch.setattr(library.shutil,'copy2',copy)
    library.publish_file(job,source,destination)
    assert observed[0]['phase']=='copying' and observed[0]['progress']==50
    assert observed[0]['copied_bytes']==500
    assert destination.read_bytes()==source.read_bytes() and snapshot(ident)=={}
