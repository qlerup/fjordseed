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
    monkeypatch.setattr('conversion_media.probe',Mock(return_value={'streams':[{'codec_type':'video'}]}))
    monkeypatch.setattr('conversion_media.validate_file',Mock())
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
    from dolby_backup import sidecar
    sidecar(Path(job['stage'])/DIRECTORY/'result'/job['output']).write_bytes(b'dv backup')
    assert library.reconcile(api,rows)==[]
    assert api.call_args.args==('torrents/setLocation',{'hashes':row['hash'],'location':job['seed']})
    move_by_qbit(film,job)
    assert library.reconcile(api,rows)==[]
    assert (Path(job['seed'])/'film.mp4').read_bytes()==b'original video'
    assert (Path(job['seed'])/'film.srt').read_bytes()==b'subtitles'
    assert (current/'film.mkv').read_bytes()==b'converted-film.mp4'
    assert sidecar(current/'film.mkv').read_bytes()==b'dv backup'
    assert library.reconcile(api,rows)==[]
    assert sidecar(current/'film.mkv').exists()
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
    monkeypatch.setattr('conversion_media.probe',Mock(return_value={'streams':[{'codec_type':'video'}]}))
    monkeypatch.setattr('conversion_media.validate_file',Mock(side_effect=ValueError('Missing subtitles')))
    with pytest.raises(ValueError):shared.complete(film[-1],job['id'],'pc')
    assert library.reconcile(film[-1],film[3])==[]
    assert (film[1]/'film.mp4').read_bytes()==b'original video'
    assert not any(c.args[0]=='torrents/setLocation' for c in film[-1].call_args_list)


def test_server_fallback_uses_scoped_snapshot_and_same_verified_publication(film,monkeypatch):
    command=shared.queue(film[-1],{'device':'pc','name':'Movie/film.mp4',
        'size':(film[0]/'Movie/film.mp4').stat().st_size,'media_folder':r'M:\Bibliotek','bitrate':30,'executor':'server'})
    job=shared.owned(command['id'],'pc');stage=Path(job['stage']);work=stage/DIRECTORY
    assert command['executor']=='server'
    request=json.loads((work/'request.json').read_text())
    assert request['executor']=='server' and request['shared'] is True
    assert os.path.samefile(stage/job['selected'],Path(job['source']))
    encoded(command,film,monkeypatch)
    assert library.reconcile(film[-1],film[3])==[]
    move_by_qbit(film,job)
    assert library.reconcile(film[-1],film[3])==[]
    assert shared.status(film[-1],job['id'],'pc')['state']=='completed'
    assert (Path(job['seed'])/'film.mp4').read_bytes()==b'original video'


def test_pc_claim_and_server_fallback_are_mutually_exclusive(film):
    command=queue(film)
    assert shared.status(film[-1],command['id'],'pc')['claimed'] is False
    claimed=shared.status(film[-1],command['id'],'pc',claim=True)
    assert claimed['claimed'] is True
    with pytest.raises(ValueError,match='startet job'):shared.fallback(film[-1],command['id'],'pc')


def test_unclaimed_pc_job_can_be_taken_by_server_but_then_pc_cannot_start(film):
    command=queue(film)
    assert shared.fallback(film[-1],command['id'],'pc')['executor']=='server'
    with pytest.raises(ValueError,match='serverens GPU'):
        shared.status(film[-1],command['id'],'pc',claim=True)


def test_missing_skipped_torrent_file_does_not_leave_an_unreachable_pending_job(film):
    film[4].append({'name':'missing.bin','size':12,'priority':0})
    with pytest.raises(ValueError):queue(film)
    assert not library.pending(film[2]['hash'])
    assert (film[1]/'film.mp4').read_bytes()==b'original video'


def test_workspace_cannot_be_created_inside_the_folder_qbittorrent_will_move(film):
    current=film[1];release=current/'Release';release.mkdir()
    for entry in film[4]:
        old=entry['name'];(current/old).rename(release/old);entry['name']='Release/'+old
    with pytest.raises(ValueError,match='ovenover'):
        shared.queue(film[-1],{'device':'pc','name':'film.mp4','size':14,'media_folder':r'M:\Bibliotek','bitrate':30})
    assert not library.pending(film[2]['hash'])
    assert (release/'film.mp4').read_bytes()==b'original video'


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
