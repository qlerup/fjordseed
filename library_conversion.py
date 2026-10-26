"""Convert retained library files, with qBittorrent-owned original relocation."""
import hashlib
import errno
import json
import os
from pathlib import Path
import shutil
import time
import uuid

import download_storage as storage
from conversion import DIRECTORY, checked, safe_relative
from state import atomic

VIDEO = {'.mkv', '.mp4', '.m4v', '.avi', '.mov', '.ts', '.m2ts', '.webm'}
STABLE = {'uploading', 'stalledUP', 'forcedUP', 'queuedUP', 'stoppedUP', 'pausedUP'}


def ledger():
    return storage.CONFIG / 'library-conversions.json'


def save(jobs):
    atomic(ledger(), json.dumps(jobs))


def fingerprint(path):
    stat = checked(path).stat()
    return [stat.st_size, stat.st_mtime_ns]


def snapshot(source, target):
    try:
        os.link(source, target)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        if shutil.disk_usage(target.parent).free < source.stat().st_size + 1024**3:
            raise ValueError('Der er ikke plads til en sikker arbejdskopi på dette lager.') from None
        shutil.copy2(source, target)


def scratch(job, target):
    return checked(target.parent / ('.fjordseed-publish-' + job['id'] + '-' + key(target)[:12]))


def publish_file(job, source, target):
    prepared = scratch(job, target)
    if target.exists():
        if os.path.samefile(source, target):
            return
        if prepared.exists() and os.path.samefile(prepared, target) and fingerprint(prepared) == fingerprint(source):
            return
        raise ValueError('En ny fil findes på bibliotekets plads. Ingen filer overskrives.')
    try:
        os.link(source, target)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        # A pooled library can place the buffer on a different underlying disk.
        # Prepare a complete copy beside the final path, then publish exclusively.
        if prepared.exists() and fingerprint(prepared) != fingerprint(source):
            prepared.unlink()
        if not prepared.exists():
            if shutil.disk_usage(target.parent).free < source.stat().st_size + 1024**3:
                raise ValueError('Der er ikke plads til den konverterede film på bibliotekets disk.')
            shutil.copy2(source, prepared)
        os.link(prepared, target)


def key(path):
    return hashlib.sha256(str(path).encode()).hexdigest()


def selected_files(api, row):
    entries = api('torrents/files?hash=' + row['hash']).json()
    if not isinstance(entries, list) or len(entries) > 10000:
        raise ValueError('Torrentens filliste kunne ikke kontrolleres.')
    result = []
    for entry in entries:
        if entry.get('priority', 1) == 0:
            continue
        name = str(safe_relative(entry.get('name')))
        if type(entry.get('size')) is not int or entry['size'] < 0:
            raise ValueError('Torrentens filstørrelse er ugyldig.')
        result.append({'name': name, 'size': entry['size']})
    return result


def marker(path):
    return path.with_name(path.name + '.fjordseed.json')


def converted(path):
    data = storage.read(checked(marker(path)), {})
    if data.get('version') == 1 and data.get('output_size') == path.stat().st_size:
        return data
    report_path = checked(path.with_suffix('.json'))
    report = storage.read(report_path, {})
    if (report.get('verified') is True and str(report.get('gpu_encoder', '')).startswith('NVEncC ')
            and str(report.get('output', '')).replace('\\', '/').rsplit('/', 1)[-1] == path.name
            and type(report.get('video_mbps_target')) is int):
        return {'bitrate': report['video_mbps_target'], 'converted_at': report_path.stat().st_mtime}
    # Recognize movies published by the existing download conversion pipeline.
    for parent in (path.parent, *path.parents):
        receipt = storage.read(checked(parent / '.fjordseed-converted.json'), {})
        if receipt.get('id') and path.relative_to(parent).as_posix() in receipt.get('files', []):
            return {'bitrate': receipt.get('bitrate'), 'converted_at': receipt.get('converted_at')}
        if parent == storage.download_root():
            break
    return None


def inventory(api):
    root = checked(storage.download_root())
    rows = api('torrents/info').json()
    owners = {}
    for row in rows:
        current = row.get('save_path', '').rstrip('/')
        if not storage.managed_directory(current):
            continue
        for entry in selected_files(api, row):
            path = Path(current) / entry['name']
            if path.is_relative_to(root):
                owners.setdefault(str(path), []).append(row)
    jobs = storage.read(ledger(), {})
    active = {j['source']: j for j in jobs.values() if j.get('phase') not in ('published', 'cancelled')}
    items = []
    truncated = False
    for folder, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in ('seedingmappe', 'Seeder')
                         and not (Path(folder) / d).is_symlink())
        for name in sorted(files):
            path = Path(folder) / name
            if path.suffix.lower() not in VIDEO or path.is_symlink():
                continue
            if len(items) >= 5000:
                truncated = True
                break
            checked(path)
            flag = converted(path)
            matches = owners.get(str(path), [])
            reason = ''
            if len(matches) != 1:
                reason = 'Ingen entydig torrent til filen. Originalen skal kunne flyttes via qBittorrent.'
            elif matches[0].get('progress') != 1 or matches[0].get('state') not in STABLE:
                reason = 'Torrenten skal være færdig og må ikke være under flytning.'
            job = active.get(str(path))
            if flag:
                reason = 'Filen er allerede konverteret.'
            if job:
                reason = 'Der er allerede et konverteringsjob til filen.'
            items.append({'id': key(path), 'name': path.relative_to(root).as_posix(),
                          'size': path.stat().st_size, 'converted': flag,
                          'eligible': not reason, 'reason': reason,
                          'job': public_job(job) if job else None,
                          '_row': matches[0] if len(matches) == 1 else None, '_path': str(path)})
        if truncated:
            break
    return {'items': items, 'truncated': truncated}


def public_job(job):
    work = Path(job['stage']) / DIRECTORY
    result = storage.read(checked(work / 'status.json'), {})
    return {'id': job['id'], 'bitrate': job['bitrate'], 'phase': job['phase'],
            'state': 'error' if job.get('error') else result.get('state', job['phase']),
            'detail': job.get('error') or result.get('detail', ''),
            'progress': result.get('progress', 0)}


def listing(api):
    result = inventory(api)
    for item in result['items']:
        item.pop('_row', None)
        item.pop('_path', None)
    result['jobs'] = [{**public_job(j), 'name': Path(j['source']).relative_to(j['root']).as_posix()}
                      for j in storage.read(ledger(), {}).values() if j['phase'] not in ('published', 'cancelled')]
    return result


def queue(api, ident, bitrate):
    if type(bitrate) is not int or bitrate not in (20, 30, 40):
        raise ValueError('Vælg 20, 30 eller 40 Mbps.')
    with storage.transaction() as entries:
        item = next((i for i in inventory(api)['items'] if i['id'] == ident), None)
        if not item or not item['eligible']:
            raise ValueError(item['reason'] if item else 'Filen findes ikke i Behold.')
        row = item['_row']
        jobs = storage.read(ledger(), {})
        if any(j['hash'] == row['hash'] and j['phase'] not in ('published', 'cancelled') for j in jobs.values()):
            raise ValueError('Torrenten har allerede et konverteringsjob.')
        if any(entries.get(row.get(k), {}).get('convert') for k in ('hash', 'infohash_v1', 'infohash_v2')):
            raise ValueError('Torrenten har allerede en oprindelig konverteringspolitik.')
        root = checked(storage.download_root())
        current = checked(row['save_path'].rstrip('/'))
        if not current.is_relative_to(root):
            raise ValueError('Originalen ligger uden for Behold.')
        files = selected_files(api, row)
        # Check all torrent owners, including torrents whose save_path differs.
        paths = {str(current / f['name']) for f in files}
        for other in api('torrents/info').json():
            if other['hash'] == row['hash'] or not storage.managed_directory(other.get('save_path', '')):
                continue
            if any(str(Path(other['save_path']) / f['name']) in paths for f in selected_files(api, other)):
                raise ValueError('Originalfilerne deles af flere torrents. Flytning er ikke sikker.')
        selected = Path(item['_path']).relative_to(current).as_posix()
        output = str(Path(selected).with_suffix('.mkv'))
        if output != selected and output in {f['name'] for f in files}:
            raise ValueError('Der findes allerede en MKV med samme navn.')
        if output != selected and checked(current / output).exists():
            raise ValueError('Der findes allerede en fil på den konverterede films plads.')
        if checked(marker(current / output)).exists():
            raise ValueError('Der findes allerede konverteringsoplysninger til filmen.')
        jobid = uuid.uuid4().hex
        stage = checked(root / storage.BUFFER / ('library-' + jobid))
        stage.mkdir(parents=True, exist_ok=False)
        job = {'id': jobid, 'hash': row['hash'], 'root': str(root), 'original': str(current),
               'source': item['_path'], 'selected': selected, 'output': output, 'files': files,
               'stage': str(stage), 'seed': str(storage.seeding_root() / (storage.download_name(row.get('name','Film'))[:100] + '-' + jobid[:8])),
               'bitrate': bitrate, 'phase': 'preparing', 'created_at': time.time()}
        jobs[jobid] = job
        save(jobs)
        try:
            for entry in files:
                source = checked(current / entry['name'])
                if not source.is_file() or source.stat().st_size != entry['size']:
                    raise ValueError('Originalfilen er ændret eller ikke færdig.')
                entry['fingerprint'] = fingerprint(source)
                target = checked(stage / entry['name'])
                target.parent.mkdir(parents=True, exist_ok=True)
                # Same filesystem, no duplicate 4K-sized copy, no mutable symlink.
                snapshot(source, target)
            work = checked(stage / DIRECTORY)
            work.mkdir()
            request = {'version': 1, 'id': jobid, 'executor': 'pc', 'bitrate': bitrate,
                       'files': [{'name': selected, 'size': Path(item['_path']).stat().st_size}]}
            atomic(work / 'request.json', json.dumps(request), mode=0o644)
            job['phase'] = 'queued'
            save(jobs)
        except Exception:
            job['error'] = 'Jobbet kunne ikke klargøres. Originalerne er bevaret.'
            save(jobs)
            raise
        return public_job(job)


def pending(ident):
    return any(j['hash'] == ident and j['phase'] not in ('published', 'cancelled')
               for j in storage.read(ledger(), {}).values())


def verify_sources(job, base):
    for entry in job['files']:
        if fingerprint(checked(base / entry['name'])) != entry['fingerprint']:
            raise ValueError('Originalfilerne er ændret. Biblioteket erstattes ikke.')


def reconcile(api, rows):
    if not ledger().exists():
        return []
    errors = []
    with storage.transaction() as entries:
        jobs = storage.read(ledger(), {})
        for job in jobs.values():
            try:
                advance(api, rows, entries, jobs, job)
                job.pop('error', None)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                job['error'] = str(exc)
                errors.append(str(exc))
            save(jobs)
    return errors


def advance(api, rows, entries, jobs, job):
    stage = checked(job['stage'])
    if job['phase'] in ('published', 'cancelled'):
        for entry in job['files']:
            name = job['output'] if entry['name'] == job['selected'] else entry['name']
            scratch(job, Path(job['original']) / name).unlink(missing_ok=True)
        if stage.is_dir():
            shutil.rmtree(stage)
        return
    row = next((r for r in rows if r['hash'] == job['hash']), None)
    if not row:
        raise ValueError('Torrenten findes ikke længere. Originalens placering skal kontrolleres.')
    work = checked(stage / DIRECTORY)
    state = storage.read(work / 'status.json', {})
    if job['phase'] == 'preparing':
        raise ValueError('Klargøringen blev afbrudt. Originalerne er bevaret.')
    if job['phase'] == 'queued' and state.get('state') != 'ready':
        return
    if row.get('progress') != 1 or row.get('state') not in STABLE:
        return
    original = checked(job['original'])
    seed = checked(job['seed'])
    result = checked(work / 'result')
    receipt = storage.read(checked(result / '.fjordseed-converted.json'), {})
    if state.get('id') != job['id'] or receipt.get('id') != job['id'] or receipt.get('files') != [job['output']]:
        raise ValueError('Kvitteringen fra pc-konverteringen matcher ikke filmen.')
    current = str(row.get('save_path', '')).rstrip('/')
    if current == str(original):
        verify_sources(job, original)
        if job['output'] != job['selected'] and checked(original / job['output']).exists():
            raise ValueError('Der findes allerede en fil på den konverterede films plads.')
        # Another torrent may have been added after this job was queued.
        paths = {str(original / f['name']) for f in job['files']}
        for other in rows:
            if other['hash'] != row['hash'] and storage.managed_directory(other.get('save_path', '')):
                if any(str(Path(other['save_path']) / f['name']) in paths for f in selected_files(api, other)):
                    raise ValueError('En anden torrent bruger originalfilerne. Flytning er sat på pause.')
        if seed.exists() and any(seed.iterdir()):
            raise ValueError('Seedingmappen indeholder allerede filer. Flytningen skal kontrolleres.')
        seed.mkdir(parents=True, exist_ok=True)
        job['phase'] = 'moving'
        # Persist before asynchronous qBittorrent setLocation; a restart can retry.
        if time.time() - job.get('move_requested_at', 0) > 30:
            job['move_requested_at'] = time.time()
            save(jobs)
            if row.get('auto_tmm'):
                api('torrents/setAutoManagement', {'hashes': row['hash'], 'enable': 'false'})
            api('torrents/setLocation', {'hashes': row['hash'], 'location': str(seed)})
        return
    if job['phase'] != 'moving' or current != str(seed):
        raise ValueError('Torrentens placering er ændret. Ingen biblioteksfiler overskrives.')
    verify_sources(job, seed)
    # Only after qBittorrent confirms its new location may the library be filled.
    for entry in job['files']:
        name = job['output'] if entry['name'] == job['selected'] else entry['name']
        target = checked(original / name)
        source = checked(result / name) if entry['name'] == job['selected'] else checked(stage / entry['name'])
        if not source.is_file():
            raise ValueError('En kontrolleret resultatfil mangler.')
        target.parent.mkdir(parents=True, exist_ok=True)
        publish_file(job, source, target)
    output = checked(original / job['output'])
    flag = {'version': 1, 'id': job['id'], 'bitrate': job['bitrate'], 'converted_at': time.time(),
            'original_size': next(f['size'] for f in job['files'] if f['name'] == job['selected']),
            'output_size': output.stat().st_size}
    if marker(output).exists() and storage.read(checked(marker(output)), {}).get('id') != job['id']:
        raise ValueError('Der findes allerede andre konverteringsoplysninger til filmen.')
    atomic(marker(output), json.dumps(flag), mode=0o644)
    for field in ('hash', 'infohash_v1', 'infohash_v2'):
        ident = row.get(field)
        if ident:
            old = entries.get(ident, {})
            entries[ident] = {**old, 'stage': str(seed), 'target': str(original),
                              'published': True, 'library_replaced': True}
    # Write the new seeding path before marking completion. A crash must never
    # allow the normal retained-file migration to move originals back again.
    atomic(storage.CONFIG / 'download-storage.json', json.dumps(entries))
    job['phase'] = 'published'
    save(jobs)


def retry(ident):
    with storage.transaction():
        jobs = storage.read(ledger(), {})
        job = jobs.get(ident)
        if not job or job['phase'] != 'queued':
            raise ValueError('Jobbet kan ikke genstartes i denne fase.')
        work = checked(Path(job['stage']) / DIRECTORY)
        status = storage.read(work / 'status.json', {})
        if status.get('state') != 'error':
            raise ValueError('Jobbet er ikke fejlet.')
        atomic(work / 'status.json', json.dumps({'id': ident, 'state': 'queued', 'progress': 0}), mode=0o644)
        job.pop('error', None)
        save(jobs)


def cancel(ident):
    with storage.transaction():
        jobs = storage.read(ledger(), {})
        job = jobs.get(ident)
        if not job or job['phase'] not in ('preparing', 'queued'):
            raise ValueError('Jobbet kan ikke annulleres, når qBittorrent er begyndt at flytte.')
        stage = checked(job['stage'])
        job['phase'] = 'cancelled'
        save(jobs)
        # Only disposable hard links and conversion output. The canonical files
        # are still in Behold; qBittorrent has not been asked to move anything.
        shutil.rmtree(stage)
