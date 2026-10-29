"""Opt-in native qBittorrent test; use only inside an isolated test container."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import pytest
import requests

import download_storage as storage
import library_conversion as library
from conversion import DIRECTORY

pytestmark = pytest.mark.skipif(os.environ.get('FJORDSEED_TEST_QBIT_BINARY') != '1',
                                reason='Requires disposable network-isolated qBittorrent container')


def bencode(value):
    if isinstance(value, int):
        return b'i' + str(value).encode() + b'e'
    if isinstance(value, bytes):
        return str(len(value)).encode() + b':' + value
    if isinstance(value,list):return b'l'+b''.join(bencode(v) for v in value)+b'e'
    if isinstance(value, dict):
        return b'd' + b''.join(bencode(k) + bencode(v) for k, v in sorted(value.items())) + b'e'
    raise TypeError()


@pytest.mark.parametrize('shared_mode',[False,True])
@pytest.mark.parametrize('cross_disk',[False,True])
def test_native_move_continues_seeding_original_and_publishes_converted_copy(tmp_path, monkeypatch,shared_mode,cross_disk):
    binary = shutil.which('qbittorrent-nox')
    assert binary, 'This test must use a real qBittorrent binary'
    config = tmp_path / 'profile' / 'qBittorrent' / 'config'
    config.mkdir(parents=True)
    (config / 'qBittorrent.conf').write_text(
        '[LegalNotice]\nAccepted=true\n[Preferences]\nWebUI\\Address=127.0.0.1\n'
        'WebUI\\Port=18080\nWebUI\\LocalHostAuth=false\nConnection\\UPnP=false\n')
    root = tmp_path / 'library'
    current = root / 'Movie'
    current.mkdir(parents=True)
    original = b'original torrent payload' * 100
    video_name='Release/film.mkv' if shared_mode else 'film.mkv'
    (current/video_name).parent.mkdir(exist_ok=True)
    (current / video_name).write_bytes(original)
    info = {b'name': b'film.mkv', b'length': len(original), b'piece length': 16384,
            b'pieces': hashlib.sha1(original).digest()}
    companions={'Release/Subs/film.en.srt':b'original english subtitle','Release/film.nfo':b'original release information'} if shared_mode else {}
    if shared_mode:
        payload=original+b''.join(companions.values())
        info={b'name':b'Release',b'piece length':16384,b'pieces':hashlib.sha1(payload).digest(),
              b'files':[{b'length':len(content),b'path':[p.encode() for p in Path(name).parts[1:]]}
                        for name,content in [(video_name,original),*companions.items()]]}
        for name,content in companions.items():
            path=current/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
        (current/'Release/film.da.srt').write_bytes(b'loose Danish subtitle')
    ident = hashlib.sha1(bencode(info)).hexdigest()
    torrent = bencode({b'announce': b'http://127.0.0.1:9/announce', b'info': info})
    session = requests.Session()
    seed_root=Path(tempfile.mkdtemp(prefix='fjordseed-native-test-',dir='/dev/shm')) if cross_disk else tmp_path/'Seeder'
    if cross_disk:assert seed_root.stat().st_dev != current.stat().st_dev
    session.trust_env = False
    base = 'http://127.0.0.1:18080/api/v2/'
    def api(path, data=None):
        result = session.get(base + path, timeout=5) if data is None else session.post(base + path, data=data, timeout=5)
        result.raise_for_status()
        return result
    with (tmp_path / 'qbit.log').open('w') as log:
        process = subprocess.Popen([binary, '--profile=' + str(tmp_path / 'profile'), '--webui-port=18080'],
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                try:
                    api('app/version')
                    break
                except requests.RequestException:
                    time.sleep(.1)
            else:
                pytest.fail('Native qBittorrent did not start: ' + (tmp_path / 'qbit.log').read_text())
            added = session.post(base + 'torrents/add', files={'torrents': ('film.torrent', torrent)},
                                 data={'savepath': str(current), 'skip_checking': 'true'}, timeout=5)
            added.raise_for_status()
            assert added.text == 'Ok.' or added.json().get('success_count') == 1
            for _ in range(100):
                rows = api('torrents/info').json()
                if rows and rows[0]['progress'] == 1 and rows[0]['state'] in library.STABLE:
                    break
                time.sleep(.1)
            else:
                pytest.fail('Synthetic torrent did not become complete')
            monkeypatch.setattr(storage, 'download_root', lambda: root)
            monkeypatch.setattr(storage, 'seeding_root', lambda: seed_root)
            monkeypatch.setattr(storage, 'managed_directory', lambda value: bool(value) and Path(value).is_relative_to(root))
            settings = tmp_path / 'settings.json'
            settings.write_text(json.dumps({'conversion_enabled': True}))
            monkeypatch.setattr(storage, 'SETTINGS', settings)
            if shared_mode:
                import shared_library
                result=shared_library.queue(api,{'device':'test-pc','media_folder':r'M:\Bibliotek',
                    'name':(current/video_name).relative_to(root).as_posix(),'size':len(original),'bitrate':30})
            else:result = library.queue(api, library.key(current / video_name), 30)
            job = storage.read(library.ledger(), {})[result['id']]
            work = Path(job['stage']) / DIRECTORY
            output=work/'result'/video_name
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_bytes(b'verified converted result')
            if shared_mode:
                from unittest.mock import Mock
                output.with_suffix('.json').write_text(json.dumps({'verified':True,'video_mbps_target':30,'gpu_encoder':'NVEncC test'}))
                monkeypatch.setattr('converter_worker.probe',Mock(return_value={}))
                monkeypatch.setattr('converter_worker.validate',Mock())
                shared_library.complete(api,job['id'],'test-pc')
            else:
                (work / 'result' / '.fjordseed-converted.json').write_text(json.dumps({'id': job['id'], 'files': [video_name]}))
                (work / 'status.json').write_text(json.dumps({'id': job['id'], 'state': 'ready'}))
            for _ in range(100):
                errors = library.reconcile(api, api('torrents/info').json())
                assert not errors, errors
                if not library.pending(ident):
                    break
                time.sleep(.1)
            else:
                pytest.fail('Native relocation/publication did not finish')
            assert (current / video_name).read_bytes() == b'verified converted result'
            assert (Path(job['seed']) / video_name).read_bytes() == original
            if cross_disk:
                saved=storage.read(library.ledger(),{})[job['id']]
                assert saved.get('verified_seed'), 'The real cross-volume copy must pass content validation'
            for name,content in companions.items():
                assert (Path(job['seed'])/name).read_bytes()==content
                assert (current/name).read_bytes()==content
                assert not os.path.samefile(current/name,Path(job['seed'])/name)
            if shared_mode:assert (current/'Release/film.da.srt').read_bytes()==b'loose Danish subtitle'
            assert api('torrents/info').json()[0]['save_path'].rstrip('/') == job['seed']
            # Rechecking verifies that qBittorrent still reads the exact torrent
            # bytes at the new location, rather than the converted library file.
            api('torrents/recheck', {'hashes': ident})
            time.sleep(.3)
            for _ in range(100):
                row = api('torrents/info').json()[0]
                if row['state'] in library.STABLE and row['progress'] == 1:
                    break
                time.sleep(.1)
            else:
                pytest.fail('Torrent did not continue seeding after recheck')
        finally:
            process.terminate()
            process.wait(timeout=20)
            session.close()
            if cross_disk:shutil.rmtree(seed_root)
