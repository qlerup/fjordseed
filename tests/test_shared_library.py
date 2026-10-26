import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

import shared_library as shared
import library_conversion as library
import download_storage as storage
from conversion import DIRECTORY
from test_library_conversion import film,move_by_qbit


def queue(film,name='Movie/film.mp4'):
    return shared.queue(film[-1],{'device':'pc','name':name,'size':(film[0]/name).stat().st_size,
        'media_folder':r'M:\Bibliotek','bitrate':30})


def encoded(command,film,monkeypatch):
    job=shared.owned(command['id'],'pc')
    work=Path(job['stage'])/DIRECTORY
    output=work/'result'/job['output']
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(b'converted-'+Path(job['selected']).name.encode())
    output.with_suffix('.json').write_text(json.dumps({'verified':True,'video_mbps_target':30,'gpu_encoder':'NVEncC 9.39'}))
    monkeypatch.setattr('converter_worker.probe',Mock(return_value={}))
    monkeypatch.setattr('converter_worker.validate',Mock())
    shared.complete(film[-1],job['id'],'pc')
    return shared.owned(job['id'],'pc')


def test_shared_queue_never_snapshots_input_and_validates_before_native_move(film,monkeypatch):
    root,current,row,rows,files,api=film
    (current/'film.da.srt').write_bytes(b'loose subtitle')
    command=queue(film)
    job=shared.owned(command['id'],'pc')
    assert command['action']=='convert' and command['work'].startswith('.fjordseed-shared/')
    assert not (Path(job['stage'])/'film.mp4').exists()
    assert not (Path(job['stage'])/DIRECTORY/'request.json').exists()
    assert library.reconcile(api,rows)==[]
    assert not any(c.args[0]=='torrents/setLocation' for c in api.call_args_list)
    job=encoded(command,film,monkeypatch)
    assert library.reconcile(api,rows)==[]
    assert api.call_args.args==('torrents/setLocation',{'hashes':row['hash'],'location':job['seed']})
    move_by_qbit(film,job)
    assert library.reconcile(api,rows)==[]
    assert (Path(job['seed'])/'film.mp4').read_bytes()==b'original video'
    assert (Path(job['seed'])/'film.srt').read_bytes()==b'subtitles'
    assert (current/'film.mkv').read_bytes()==b'converted-film.mp4'
    assert (current/'film.da.srt').read_bytes()==b'loose subtitle'
    assert not os.path.samefile(current/'film.srt',Path(job['seed'])/'film.srt')
    (current/'film.srt').write_bytes(b'edited library subtitle')
    assert (Path(job['seed'])/'film.srt').read_bytes()==b'subtitles'
    assert shared.status(api,job['id'],'pc')['state']=='completed'
    with pytest.raises(ValueError):shared.complete(api,job['id'],'other-pc')


def test_invalid_result_leaves_entire_torrent_untouched(film,monkeypatch):
    command=queue(film)
    job=shared.owned(command['id'],'pc');work=Path(job['stage'])/DIRECTORY
    output=work/'result'/job['output'];output.write_bytes(b'bad video')
    output.with_suffix('.json').write_text(json.dumps({'verified':True,'video_mbps_target':30,'gpu_encoder':'NVEncC 9.39'}))
    monkeypatch.setattr('converter_worker.probe',Mock(return_value={}))
    monkeypatch.setattr('converter_worker.validate',Mock(side_effect=ValueError('Missing subtitles')))
    with pytest.raises(ValueError):shared.complete(film[-1],job['id'],'pc')
    assert library.reconcile(film[-1],film[3])==[]
    assert (film[1]/'film.mp4').read_bytes()==b'original video'
    assert not any(c.args[0]=='torrents/setLocation' for c in film[-1].call_args_list)


def test_second_episode_reuses_the_complete_seeded_pack(film,monkeypatch):
    root,current,row,rows,files,api=film
    (current/'episode2.mkv').write_bytes(b'original episode two')
    files.append({'name':'episode2.mkv','size':20,'priority':1})
    first=encoded(queue(film),film,monkeypatch)
    library.reconcile(api,rows);move_by_qbit(film,first);library.reconcile(api,rows)
    seed=Path(first['seed'])
    before=(seed/'episode2.mkv').read_bytes()
    second=encoded(queue(film,'Movie/episode2.mkv'),film,monkeypatch)
    assert second['reuse_seeding'] and second['seed']==first['seed']
    api.reset_mock()
    assert library.reconcile(api,rows)==[]
    assert (current/'episode2.mkv').read_bytes()==b'converted-episode2.mkv'
    assert (seed/'episode2.mkv').read_bytes()==before
    assert (seed/'film.mp4').read_bytes()==b'original video'
    assert (current/'film.mkv').read_bytes()==b'converted-film.mp4'
    assert not any(c.args[0]=='torrents/setLocation' for c in api.call_args_list)
