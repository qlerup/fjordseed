"""Copy selected tracks between two library films with MKVToolNix."""
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager

import conversion_workflow as workflow
import download_storage as storage
import library_conversion as library
from state import atomic


def folder():
    path = storage.CONFIG/'track-merges'
    path.mkdir(parents=True, exist_ok=True)
    return path


def read(): return storage.read(folder()/'jobs.json', [])
def save(jobs): atomic(folder()/'jobs.json', json.dumps(jobs, ensure_ascii=False))


def identify(path):
    try:
        result = subprocess.run(['mkvmerge', '-J', str(path)], capture_output=True,
                                text=True, encoding='utf-8', timeout=30)
        media = json.loads(result.stdout)
        if result.returncode or not media.get('container', {}).get('recognized'):
            raise ValueError()
        return media
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ValueError('Filens spor kunne ikke læses med MKVToolNix.') from None


def eligible(item):
    row = item.get('_row') or {}
    return (not item.get('job') and item.get('torrent_status') != 'ambiguous'
            and (not row or row.get('progress') == 1 and row.get('state') in library.STABLE))


def public(item):
    path = Path(item['_path'])
    return {'id': item['id'], 'name': item['name'], 'title': (item.get('_row') or {}).get('name') or path.stem,
            'size': item['size'], 'eligible': eligible(item)}


def resolve(api, ident):
    item = next((i for i in library.inventory(api)['items'] if i['id'] == ident), None)
    if not item: raise ValueError('Filmen findes ikke længere i biblioteket.')
    if not eligible(item): raise ValueError('Vent til download eller konvertering er færdig.')
    return item, library.checked(Path(item['_path']))


def details(api, ident):
    item, path = resolve(api, ident)
    stamp = library.fingerprint(path)
    media = identify(path)
    tracks = []
    # FFprobe's profile may expose Atmos/JOC even when MKVToolNix only names E-AC-3.
    try: profiles = workflow.media_info(path).get('streams', [])
    except (OSError, ValueError, subprocess.SubprocessError): profiles = []
    for kind in ('audio', 'subtitles'):
        probes = iter(s for s in profiles if s.get('codec_type') == ('subtitle' if kind == 'subtitles' else kind))
        for track in (t for t in media['tracks'] if t['type'] == kind):
            props = track.get('properties', {})
            probe = next(probes, {})
            tracks.append({'id': track['id'], 'kind': kind, 'codec': track.get('codec', 'Ukendt'),
                'profile': probe.get('profile', ''), 'language': props.get('language_ietf') or props.get('language', 'und'),
                'title': props.get('track_name', ''), 'channels': props.get('audio_channels'),
                'default': bool(props.get('default_track')), 'forced': bool(props.get('forced_track'))})
    if not any(t['type'] == 'video' for t in media['tracks']): raise ValueError('Filen har intet videospor.')
    if library.fingerprint(path) != stamp: raise ValueError('Filmen er ændret. Vælg den igen.')
    return {**public(item), 'fingerprint': workflow.browser_fingerprint(stamp),
            'duration': media.get('container', {}).get('properties', {}).get('duration', 0)/1e9, 'tracks': tracks}


def validate(api, data, *, require_import=True):
    sources = []
    for key in ('base', 'donor'):
        choice = data.get(key)
        if not isinstance(choice, dict): raise ValueError('Vælg både hovedfil og filen med ekstra spor.')
        item, path = resolve(api, choice.get('id'))
        if not workflow.fingerprint_matches(choice.get('fingerprint'), library.fingerprint(path)):
            raise ValueError('En film er ændret. Vælg filmene igen.')
        media = identify(path)
        if not any(t['type'] == 'video' for t in media['tracks']): raise ValueError('Begge filer skal indeholde video.')
        selected = choice.get('tracks')
        allowed = {t['id'] for t in media['tracks'] if t['type'] in ('audio', 'subtitles')}
        if (not isinstance(selected, list) or len(selected) > len(allowed) or any(type(i) is not int or i not in allowed for i in selected)
                or len(set(selected)) != len(selected)):
            raise ValueError('Vælg gyldige lydspor og undertekster.')
        sources.append((item, path, media, selected))
    if sources[0][1] == sources[1][1]: raise ValueError('Vælg to forskellige filer.')
    if require_import and not sources[1][3]: raise ValueError('Vælg mindst ét spor fra den anden film.')
    offset = data.get('offset_ms', 0)
    if type(offset) not in (int, float) or not -3600000 <= offset <= 3600000 or not math.isfinite(offset) or int(offset) != offset:
        raise ValueError('Tidsforskydningen skal være hele millisekunder mellem -3600000 og 3600000.')
    return sources, int(offset)


def enqueue(api, data):
    with storage.transaction():
        sources, offset = validate(api, data)
        jobs = read()
        if sum(j['state'] in ('queued', 'running') for j in jobs) >= 100:
            raise ValueError('Flettekøen er fuld (maks. 100).')
        ident = uuid.uuid4().hex
        base = sources[0][1]
        output = base.with_name(base.stem+'.merged-'+ident[:8]+'.mkv')
        if output.exists(): raise ValueError('Resultatfilen findes allerede.')
        job = {'id': ident, 'owner': data['owner'], 'name': base.name, 'state': 'queued',
               'detail': 'Venter på fletning', 'created_at': time.time(), 'output': output.name,
               'base': data['base'], 'donor': data['donor'], 'offset_ms': offset}
        jobs.append(job); save(jobs)
    return {'ok': True, 'id': ident, 'output': output.name}


def command(sources, offset, output):
    args = ['mkvmerge', '--gui-mode', '-o', str(output)]
    for index, (_, path, media, selected) in enumerate(sources):
        for kind, flag, empty in (('audio', '--audio-tracks', '--no-audio'),
                                  ('subtitles', '--subtitle-tracks', '--no-subtitles')):
            ids = [str(t['id']) for t in media['tracks'] if t['type'] == kind and t['id'] in selected]
            args.extend([flag, ','.join(ids)] if ids else [empty])
        if index:
            args.extend(['--no-video', '--no-chapters', '--no-global-tags'])
            if not any(t['type'] == 'subtitles' and t['id'] in selected for t in media['tracks']):
                args.append('--no-attachments')
            for track in selected:
                if offset: args.extend(['--sync', f'{track}:{offset}'])
                # Appending another default track would leave player choice ambiguous.
                args.extend(['--default-track-flag', f'{track}:no'])
        args.append(str(path))
    return args


def update(ident, **fields):
    with storage.transaction():
        jobs = read(); job = next(j for j in jobs if j['id'] == ident)
        job.update(fields); save(jobs)


def verify(sources, target):
    expected = []
    for index, (_, _, media, selected) in enumerate(sources):
        expected.extend(t for t in media['tracks'] if (not index and t['type'] == 'video') or t['id'] in selected)
    actual = identify(target)['tracks']
    def signature(track):
        props = track.get('properties', {})
        # Container-specific codec_id is absent for MP4/AVI inputs. The codec
        # name identifies the actual bitstream across source/output containers.
        codec = track.get('codec')
        if codec == 'Timed Text': codec = 'SubRip/SRT'  # MP4 text becomes Matroska text.
        return (track['type'], codec, props.get('audio_channels'), props.get('audio_sampling_frequency'))
    if sorted(map(signature, expected), key=str) != sorted(map(signature, actual), key=str):
        raise ValueError('Kontrol af resultatets spor fejlede. Originalerne er bevaret.')


def process(api, job):
    temporary = None
    linked = completed = False
    try:
        sources, offset = validate(api, job)
        base = sources[0][1]
        target = library.checked(base.with_name(job['output']))
        temporary = library.checked(base.with_name('.fjordseed-merge-'+job['id']+'.partial'))
        if target.exists():
            if temporary.exists() and os.path.samefile(temporary, target):
                # Recover a crash after exclusive publication but before saving the job.
                linked = True
                verify(sources, target)
                validate(api, job)
                update(job['id'], state='done', detail='Færdig · '+target.name, progress=100)
                completed = True
                return
            raise ValueError('Resultatfilen findes allerede. Ingen filer overskrives.')
        if shutil.disk_usage(base.parent).free < sum(s[1].stat().st_size for s in sources) + 256*1024**2:
            raise ValueError('Der er ikke nok ledig plads til fletningen. Originalerne bevares.')
        temporary.unlink(missing_ok=True)
        log = folder()/(job['id']+'.log')
        with log.open('w', encoding='utf-8') as output:
            result = subprocess.run(command(sources, offset, temporary), stdout=output, stderr=subprocess.STDOUT, timeout=21600)
        if result.returncode not in (0, 1) or not temporary.is_file():
            raise ValueError('MKVToolNix kunne ikke flette sporene. Originalerne er bevaret.')
        update(job['id'], detail='Kontrollerer resultatets spor')
        verify(sources, temporary)
        with storage.transaction():
            # Publication never replaces either input, a torrent payload, or another result.
            validate(api, job)
            with temporary.open('rb+') as handle: os.fsync(handle.fileno())
            os.chmod(temporary, 0o644)
            os.link(temporary, library.checked(target))
            linked = True
            jobs = read()
            current = next(j for j in jobs if j['id'] == job['id'])
            current.update(state='done', detail='Færdig · '+target.name+(' · MKVToolNix meldte en advarsel; kontrollér afspilningen.' if result.returncode else ''), progress=100)
            save(jobs)
            completed = True
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) else 'Fletningen blev afbrudt. Originalerne er bevaret. Prøv igen.'
        update(job['id'], state='error', detail=detail)
    finally:
        if temporary and (not linked or completed): temporary.unlink(missing_ok=True)


@contextmanager
def worker_lock():
    """OS releases the claim on crashes, including container/PID reuse."""
    with (folder()/'worker.lock').open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            handle.write(b'0'); handle.flush(); handle.seek(0)
            acquire = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: (handle.seek(0), msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1))
        else:
            import fcntl
            acquire = lambda: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(handle, fcntl.LOCK_UN)
        try: acquire()
        except OSError:
            yield False
            return
        try: yield True
        finally: release()


def tick(api):
    with worker_lock() as acquired:
        if not acquired: return {'ok': True}
        with storage.transaction():
            jobs = read()
            for running in (j for j in jobs if j['state'] == 'running'):
                running.update(state='error', detail='Serveren blev genstartet under fletningen. Prøv igen.')
            job = next((j for j in jobs if j['state'] == 'queued'), None)
            if job:
                job.update(state='running', detail='Kopierer spor uden genkodning', started_at=time.time())
                (folder()/(job['id']+'.log')).unlink(missing_ok=True)
            save(jobs)
        if job: process(api, job)
    return {'ok': True}


def jobs_for(owner):
    rows = [j for j in read() if j['owner'] == owner]
    rows = [j for j in rows if j['state'] in ('queued', 'running', 'error')] + [j for j in rows if j['state'] in ('done', 'cancelled')][-20:]
    result = []
    for row in rows:
        public_job = {k: row.get(k) for k in ('id', 'name', 'state', 'detail', 'output', 'progress')}
        if row['state'] == 'running':
            log = folder()/(row['id']+'.log')
            if log.exists():
                with log.open('rb') as handle:
                    handle.seek(max(0, log.stat().st_size-8192))
                    matches = re.findall(rb'#GUI#progress (\d+)%', handle.read())
                if matches: public_job['progress'] = min(99, int(matches[-1]))
        result.append(public_job)
    return {'jobs': result}


def dispatch(api, action, data):
    if action in ('analyse', 'preview'):
        from merge_sync import run
        return run(api, action, data)
    if action == 'list':
        result = library.inventory(api)
        return {'items': [public(i) for i in result['items']], 'truncated': result['truncated']}
    if action == 'details': return details(api, data.get('id'))
    if action == 'queue': return enqueue(api, data)
    if action == 'jobs': return jobs_for(data['owner'])
    if action == 'tick': return tick(api)
    if action in ('cancel', 'retry'):
        with storage.transaction():
            jobs = read()
            job = next((j for j in jobs if j['id'] == data.get('id') and j['owner'] == data['owner']), None)
            if not job: raise ValueError('Fletningen findes ikke.')
            if action == 'cancel' and job['state'] in ('queued', 'error'):
                job.update(state='cancelled', detail='Annulleret · originalerne er bevaret')
            elif action == 'retry' and job['state'] == 'error':
                validate(api, job)
                job.update(state='queued', detail='Venter på fletning', progress=None)
            else: raise ValueError('Handlingen er ikke mulig for dette job.')
            save(jobs)
        return {'ok': True}
    raise ValueError('Ukendt flettehandling.')
