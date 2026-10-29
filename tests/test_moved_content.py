import hashlib
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

import library_conversion as library
import download_storage as storage
import shared_library as shared
from test_library_conversion import film, enqueue, ready, move_by_qbit


def encode(value):
    if isinstance(value, bytes):return str(len(value)).encode()+b':'+value
    if isinstance(value, int):return b'i'+str(value).encode()+b'e'
    if isinstance(value, list):return b'l'+b''.join(map(encode,value))+b'e'
    return b'd'+b''.join(encode(k)+encode(v) for k,v in sorted(value.items()))+b'e'


def torrent(job, base, piece_size=7):
    # Deliberately cross file boundaries and finish with a partial piece.
    files=job['files']
    contents=b''.join((base/f['name']).read_bytes() for f in files)
    info={b'name':b'Movie',b'piece length':piece_size,
          b'pieces':b''.join(hashlib.sha1(contents[i:i+piece_size]).digest() for i in range(0,len(contents),piece_size)),
          b'files':[{b'length':f['size'],b'path':[f['name'].encode()]} for f in files]}
    return encode({b'info':info}),hashlib.sha1(encode(info)).hexdigest()


def export_for(job, base):
    # qBittorrent file names include the torrent root in multi-file torrents.
    data,ident=torrent(job,base)
    for f in job['files']:f['name']='Movie/'+f['name']
    return data,ident


@pytest.mark.parametrize('corrupt',[False,True])
def test_full_piece_check_accepts_changed_mtime_but_rejects_corruption(tmp_path,corrupt):
    seed=tmp_path/'seed';seed.mkdir()
    for name,content in [('a.mkv',b'0123456789abc'),('b.srt',b'subtitles')]:
        (seed/name).write_bytes(content)
    job={'files':[{'name':p.name,'size':p.stat().st_size,'fingerprint':library.fingerprint(p)} for p in seed.iterdir()]}
    raw,ident=export_for(job,seed)
    nested=seed/'Movie';nested.mkdir()
    for p in list(seed.iterdir()):
        if p.is_file():p.rename(nested/p.name)
    job['hash']=ident
    for p in nested.iterdir():os.utime(p,ns=(p.stat().st_atime_ns,p.stat().st_mtime_ns+1000000000))
    if corrupt:
        with (nested/'a.mkv').open('r+b') as f:f.seek(6);f.write(b'X')
    api=Mock(return_value=Mock(content=raw))
    if corrupt:
        with pytest.raises(ValueError,match='kontrolsummer'):library.verify_moved_sources(api,job,seed)
        assert 'verified_seed' not in job
    else:
        library.verify_moved_sources(api,job,seed)
        assert len(job['verified_seed'])==2
        api.reset_mock();library.verify_moved_sources(api,job,seed);api.assert_not_called()


def test_single_file_cross_disk_move_completes_without_encoding_again(film):
    root,current,row,rows,files,api=film
    # Single-file torrent: same layout as the affected Nobody 2 job.
    files[:]=[f for f in files if f['name']=='film.mp4']
    job=enqueue(film);ready(job)
    content=(current/'film.mp4').read_bytes()
    info={b'name':b'film.mp4',b'length':len(content),b'piece length':8,
          b'pieces':b''.join(hashlib.sha1(content[i:i+8]).digest() for i in range(0,len(content),8))}
    ident=hashlib.sha1(encode(info)).hexdigest()
    row['hash']=job['hash']=ident
    jobs=storage.read(library.ledger(),{});jobs[job['id']]=job;library.save(jobs)
    original_api=api.side_effect
    api.side_effect=lambda path,data=None: Mock(content=encode({b'info':info})) if path.startswith('torrents/export?') else original_api(path,data)
    assert library.reconcile(api,rows)==[]
    move_by_qbit(film,job)
    target=Path(job['seed'])/'film.mp4'
    os.utime(target,ns=(target.stat().st_atime_ns,target.stat().st_mtime_ns+1000000000))
    # Reproduce an existing job already stopped by the old timestamp check.
    jobs=storage.read(library.ledger(),{});jobs[job['id']]['error']='Originalfilerne er ændret.';library.save(jobs)
    assert library.reconcile(api,rows)==[]
    saved=storage.read(library.ledger(),{})[job['id']]
    assert saved['phase']=='published' and not saved.get('error')
    assert (current/'film.mkv').read_bytes()==b'converted'
    assert target.read_bytes()==content


def test_moving_error_is_returned_to_pc_instead_of_hidden(film):
    job=enqueue(film)
    job.update(phase='moving',error='Originalfilerne er ændret.',shared={'attempt':'a','source_signature':'x',
        'media_folder':'M:/Bibliotek','name':'film.mp4','server_root':str(film[0])})
    result=shared.command(job)
    assert result['state']=='error' and result['stage']=='error'
    assert result['detail']==job['error']
