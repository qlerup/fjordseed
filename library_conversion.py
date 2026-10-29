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
    priors={}
    for job in jobs.values():
        if job.get('phase')!='published' or not job.get('shared'):continue
        row=next((r for r in rows if r['hash']==job['hash'] and r.get('save_path','').rstrip('/')==job['seed']),None)
        if not row:continue
        for entry in job['files']:
            path=Path(job['original'])/entry['name']
            if path.is_file() and path.is_relative_to(root) and fingerprint(path)==entry['fingerprint']:
                if not any(r['hash']==row['hash'] for r in owners.get(str(path),[])):
                    owners.setdefault(str(path),[]).append(row)
                priors[str(path)]=job
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
                          '_row': matches[0] if len(matches) == 1 else None, '_path': str(path),'_prior':priors.get(str(path))})
        if truncated:
            break
    return {'items': items, 'truncated': truncated}


def public_job(job):
    work = Path(job['stage']) / DIRECTORY
    result = storage.read(checked(work / 'status.json'), {})
    return {'id': job['id'], 'bitrate': job['bitrate'], 'phase': job['phase'],
            'state': 'error' if job.get('error') else result.get('state', job['phase']),
            'detail': job.get('error') or result.get('detail', ''),
            'progress': result.get('progress', 0),
            **{k:result[k] for k in ('stage','stage_started_at','at','phase_progress') if k in result}}


def listing(api):
    result = inventory(api)
    for item in result['items']:
        item.pop('_row', None)
        item.pop('_path', None)
        item.pop('_prior',None)
    result['jobs'] = [{**public_job(j), 'name': Path(j['source']).relative_to(j['root']).as_posix()}
                      for j in storage.read(ledger(), {}).values() if j['phase'] not in ('published', 'cancelled') and not j.get('shared')]
    return result


def queue(api, ident, bitrate, shared=None):
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
        prior=item.get('_prior') if shared else None
        torrent_base=checked(row['save_path'].rstrip('/'))
        current = checked(prior['original']) if prior else torrent_base
        if not current.is_relative_to(root):
            raise ValueError('Originalen ligger uden for Behold.')
        files = selected_files(api, row)
        if shared:
            # Relocate the complete torrent, including skipped files; never
            # silently turn a partially downloaded pack into a library replacement.
            files=[]
            for entry in api('torrents/files?hash='+row['hash']).json():
                name=str(safe_relative(entry.get('name')))
                if type(entry.get('size')) is not int or entry['size']<0:raise ValueError('Ugyldig torrentfil.')
                files.append({'name':name,'size':entry['size']})
        # Check all torrent owners, including torrents whose save_path differs.
        paths = {str(torrent_base / f['name']) for f in files}
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
        if shared and not prior:
            parts=[Path(f['name']).parts for f in files]
            tops={p[0] for p in parts}
            if parts and all(len(p)>1 for p in parts) and len(tops)==1:
                torrent_folder=current/next(iter(tops))
                if Path(shared['server_root']).is_relative_to(torrent_folder):
                    raise ValueError('Vælg en mappe ovenover torrentens egen mappe i programmet, fx Bibliotek.')
        jobid = uuid.uuid4().hex
        stage = checked(Path(shared['server_root']) / '.fjordseed-shared' / jobid) if shared else checked(root / storage.BUFFER / ('library-' + jobid))
        stage.mkdir(parents=True, exist_ok=False)
        job = {'id': jobid, 'hash': row['hash'], 'root': str(root), 'original': str(current),
               'source': item['_path'], 'selected': selected, 'output': output, 'files': files,
               'stage': str(stage), 'seed': str(torrent_base if prior else storage.seeding_root() / (storage.download_name(row.get('name','Film'))[:100] + '-' + jobid[:8])),
               'bitrate': bitrate, 'phase': 'preparing', 'created_at': time.time()}
        if shared:job['shared']={**shared,'attempt':uuid.uuid4().hex}
        if prior:job['reuse_seeding']=True
        jobs[jobid] = job
        save(jobs)
        try:
            for entry in files:
                source = checked(torrent_base / entry['name'])
                if not source.is_file() or source.stat().st_size != entry['size']:
                    raise ValueError('Originalfilen er ændret eller ikke færdig.')
                entry['fingerprint'] = fingerprint(source)
                target = checked(stage / entry['name'])
                target.parent.mkdir(parents=True, exist_ok=True)
                if not shared:
                    # Same filesystem, no duplicate 4K-sized copy, no mutable symlink.
                    snapshot(source, target)
            work = checked(stage / DIRECTORY)
            work.mkdir()
            request = {'version': 1, 'id': jobid, 'executor': 'pc', 'bitrate': bitrate,
                       'files': [{'name': selected, 'size': Path(item['_path']).stat().st_size}]}
            if not shared:atomic(work / 'request.json', json.dumps(request), mode=0o644)
            else:
                (work/'result'/Path(output).parent).mkdir(parents=True,exist_ok=True)
                atomic(work/'status.json',json.dumps({'id':jobid,'state':'queued','progress':0}),mode=0o644)
            job['phase'] = 'queued'
            save(jobs)
        except Exception:
            job['error'] = 'Jobbet kunne ikke klargøres. Originalerne er bevaret.'
            if shared:job['phase']='cancelled'
            save(jobs)
            if shared and stage.is_dir():shutil.rmtree(stage)
            raise
        return public_job(job)


def pending(ident):
    return any(j['hash'] == ident and j['phase'] not in ('published', 'cancelled')
               for j in storage.read(ledger(), {}).values())


def verify_sources(job, base):
    for entry in job['files']:
        if fingerprint(checked(base / entry['name'])) != entry['fingerprint']:
            raise ValueError('Originalfilerne er ændret. Biblioteket erstattes ikke.')


def verification_pending():
    return any(j.get('phase')=='moving' and j.get('seed_check') and not j.get('error')
               for j in storage.read(ledger(),{}).values())


def verify_moved_sources(api, job, seed, *, budget_seconds=1, budget_bytes=128*1024*1024):
    """A native cross-volume copy changes mtime; verify torrent bytes instead.

    Never accept equal size alone. Verify every v1 piece (including boundaries
    between files) against the torrent's authenticated info hash. Cache only the
    fingerprints actually verified, so a later modification requires rechecking.
    Unsupported/renamed/incomplete torrents fail closed.
    """
    expected = job.get('verified_seed', {})
    actual = {f['name']: fingerprint(checked(seed/f['name'])) for f in job['files']}
    if all(actual[f['name']] == expected.get(f['name'], f['fingerprint']) for f in job['files']):
        return True
    work = checked(Path(job['stage'])/DIRECTORY) if job.get('stage') else None
    checkpoint = job.get('seed_check', {})
    if checkpoint.get('fingerprints') != actual:
        checkpoint = {'fingerprints':actual,'pieces':0,'started_at':time.time()}
    job['seed_check'] = checkpoint
    started = checkpoint['started_at']
    tick_started = time.monotonic()
    last_report = 0
    read_bytes = 0
    def report(total, done=False, force=False):
        nonlocal last_report
        now=time.time()
        if work and (now-last_report >= 1 or done or force):
            atomic(work/'status.json', json.dumps({'id':job['id'],'state':'ready','progress':100,
                'stage':'publishing' if done else 'source_verifying','stage_started_at':now if done else started,'at':now,
                'phase_progress':100 if done else (100*read_bytes/total if total else 0),
                'detail':'Indhold kontrolleret · lægger filmen i biblioteket' if done else
                    'Flytning færdig · kontrollerer originalens indhold mod torrentens kontrolsummer'}), mode=0o644)
            last_report=now
    from torrent_meta import torrent_meta
    raw = api('torrents/export?hash='+job['hash']).content
    meta = torrent_meta(raw, include_info=True)
    if job['hash'].lower() not in meta['hashes']:
        raise ValueError('Torrentens kontrolsummer matcher ikke jobbet.')
    info = meta['info']
    piece_size, pieces = info.get(b'piece length'), info.get(b'pieces')
    if type(piece_size) is not int or not 0 < piece_size <= 64*1024*1024 or not isinstance(pieces, bytes):
        raise ValueError('Den flyttede torrent kræver en understøttet indholdskontrol. Originalerne er bevaret.')
    def text(value):
        if not isinstance(value, bytes):raise ValueError('Ugyldig filsti i torrentens kontroloplysninger.')
        return value.decode('utf-8')
    name = str(safe_relative(text(info.get(b'name.utf-8', info.get(b'name')))))
    if b'files' in info:
        files = []
        for item in info[b'files']:
            parts = item.get(b'path.utf-8', item.get(b'path'))
            if not isinstance(parts, list):raise ValueError('Ugyldig filliste i torrenten.')
            relative = str(safe_relative('/'.join(text(p) for p in parts)))
            files.append((str(safe_relative(name+'/'+relative)), item.get(b'length')))
    else:
        files = [(name, info.get(b'length'))]
    if any(type(size) is not int or size < 0 for _, size in files):
        raise ValueError('Ugyldig filstørrelse i torrenten.')
    if {n:s for n,s in files} != {f['name']:f['size'] for f in job['files']}:
        raise ValueError('Torrentens fulde filliste skal matche før indholdet kan kontrolleres.')
    total = sum(size for _, size in files)
    if len(pieces) != ((total+piece_size-1)//piece_size)*20:
        raise ValueError('Torrentens kontrolsummer er ufuldstændige.')
    index = checkpoint['pieces']*20
    if type(index) is not int or not 0 <= index <= len(pieces):
        raise ValueError('Ugyldigt kontrolpunkt for originalfilen.')
    skip_bytes = checkpoint['pieces']*piece_size
    if skip_bytes > total:raise ValueError('Kontrolpunktet ligger uden for originalfilen.')
    read_bytes = skip_bytes
    tick_bytes = 0
    report(total)
    digest, filled = hashlib.sha1(), 0
    for relative, size in files:
        path = checked(seed/relative)
        if actual[relative][0] != size:raise ValueError('Den flyttede originalfil har forkert størrelse.')
        with path.open('rb') as handle:
            skipped = min(size,skip_bytes)
            handle.seek(skipped);skip_bytes -= skipped
            remaining = size-skipped
            while remaining:
                block = handle.read(min(1024*1024, piece_size-filled, remaining))
                if not block:raise ValueError('Den flyttede originalfil er ufuldstændig.')
                digest.update(block);filled += len(block);remaining -= len(block)
                read_bytes += len(block);tick_bytes += len(block);report(total)
                if filled == piece_size:
                    if digest.digest() != pieces[index:index+20]:
                        raise ValueError('Den flyttede original matcher ikke torrentens kontrolsummer. Biblioteket erstattes ikke.')
                    index += 20;digest, filled = hashlib.sha1(), 0
                    checkpoint['pieces'] = index//20
                    if read_bytes < total and (tick_bytes >= budget_bytes or time.monotonic()-tick_started >= budget_seconds):
                        if any(fingerprint(checked(seed/n)) != stamp for n,stamp in actual.items()):
                            raise ValueError('Originalfilerne ændrede sig under indholdskontrollen.')
                        report(total,force=True)
                        return False
    if filled and digest.digest() != pieces[index:index+20]:
        raise ValueError('Den flyttede original matcher ikke torrentens kontrolsummer. Biblioteket erstattes ikke.')
    if any(fingerprint(checked(seed/n)) != stamp for n, stamp in actual.items()):
        raise ValueError('Originalfilerne ændrede sig under indholdskontrollen.')
    job['verified_seed'] = actual
    job.pop('seed_check',None)
    report(total, done=True)
    return True


def reconcile(api, rows):
    if not ledger().exists():
        return []
    errors = []
    with storage.transaction() as entries:
        jobs = storage.read(ledger(), {})
        pass_started=time.monotonic()
        for job in jobs.values():
            try:
                advance(api, rows, entries, jobs, job)
                job.pop('error', None)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                job['error'] = str(exc)
                errors.append(str(exc))
            save(jobs)
            if time.monotonic()-pass_started>=1:
                break  # Multiple large jobs must share the supervisor's time budget.
    return errors


def resume_original(api, rows, jobs, job):
    if not job.get('resume_pending'):return
    row=next((r for r in rows if r['hash']==job['hash']),None)
    if not row or row.get('save_path','').rstrip('/')!=job['seed'] or row.get('progress')!=1:
        raise ValueError('Originalens placering skal bekræftes før automatisk seeding.')
    if row.get('state') in ('stoppedUP','pausedUP'):
        api('torrents/start',{'hashes':job['hash']})
    elif row.get('state') not in ('uploading','stalledUP','forcedUP','queuedUP'):
        return
    job.pop('resume_pending',None)
    save(jobs)


def advance(api, rows, entries, jobs, job):
    stage = checked(job['stage'])
    if job['phase'] in ('published', 'cancelled'):
        if job['phase']=='published':resume_original(api,rows,jobs,job)
        for entry in job['files']+job.get('extras',[]):
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
    if job.get('shared') and fingerprint(checked(result/job['output']))!=job.get('verified_result'):
        raise ValueError('Den kontrollerede konvertering er ændret. Originalerne flyttes ikke.')
    current = str(row.get('save_path', '')).rstrip('/')
    if job.get('reuse_seeding') and current==str(seed) and job['phase']=='queued':
        source_path=str(original/job['selected'])
        for other in rows:
            if other['hash']!=row['hash'] and storage.managed_directory(other.get('save_path','')):
                if any(str(Path(other['save_path'])/f['name'])==source_path for f in selected_files(api,other)):
                    raise ValueError('En anden torrent bruger bibliotekets originalkopi.')
        job.setdefault('resume_after_move',row.get('state') in ('uploading','stalledUP','forcedUP','queuedUP'))
        job['phase']='moving';save(jobs)
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
        if job.get('shared'):
            # Preserve companions before qBittorrent moves its entire storage.
            # Subtitles/artwork get independent copies, never mutable hardlinks
            # to the originals that must continue satisfying torrent hashes.
            for entry in job['files']:
                if entry['name']==job['selected']:continue
                source=checked(original/entry['name']);target=checked(stage/entry['name'])
                target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists():
                    if source.suffix.lower() in VIDEO:snapshot(source,target)
                    else:shutil.copy2(source,target)
                if fingerprint(target)!=entry['fingerprint']:raise ValueError('En ledsagefil kunne ikke bevares.')
        seed.mkdir(parents=True, exist_ok=True)
        # Capture intent before the asynchronous move can change native state.
        # A torrent explicitly paused by the user must remain paused.
        job.setdefault('resume_after_move',row.get('state') in ('uploading','stalledUP','forcedUP','queuedUP'))
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
    verified = verify_moved_sources(api, job, seed)
    save(jobs)
    if not verified:return
    # Only after qBittorrent confirms its new location may the library be filled.
    for entry in job['files']:
        name = job['output'] if entry['name'] == job['selected'] else entry['name']
        target = checked(original / name)
        source = checked(result / name) if entry['name'] == job['selected'] else checked(stage / entry['name'])
        if job.get('reuse_seeding') and entry['name']!=job['selected']:
            if target.exists():continue
            source=checked(seed/entry['name'])
            if source.suffix.lower() not in VIDEO:
                copied=checked(stage/entry['name']);copied.parent.mkdir(parents=True,exist_ok=True)
                if not copied.exists():shutil.copy2(source,copied)
                source=copied
        if not source.is_file():
            raise ValueError('En kontrolleret resultatfil mangler.')
        target.parent.mkdir(parents=True, exist_ok=True)
        if job.get('reuse_seeding') and entry['name']==job['selected'] and name==job['selected']:
            prepared=scratch(job,target)
            if not prepared.exists():snapshot(source,prepared)
            if fingerprint(prepared)!=job['verified_result']:raise ValueError('Resultatkopien er ændret.')
            if target.exists() and fingerprint(target) not in (entry['fingerprint'],job['verified_result']):
                raise ValueError('Bibliotekets fil er ændret. Ingen filer erstattes.')
            os.replace(prepared,target)
        else:publish_file(job, source, target)
    if job.get('reuse_seeding') and job['selected']!=job['output']:
        old=checked(original/job['selected'])
        if old.exists():
            expected=next(f['fingerprint'] for f in job['files'] if f['name']==job['selected'])
            if fingerprint(old)!=expected:raise ValueError('Bibliotekets originalkopi er ændret.')
            old.unlink()  # The unchanged torrent original remains at seed/selected.
    for entry in job.get('extras',[]):
        target=checked(original/entry['name']);source=checked(stage/entry['name'])
        if target.exists():
            if fingerprint(target)!=entry['fingerprint']:raise ValueError('En løs ledsagefil er ændret.')
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            publish_file(job,source,target)
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
    if job.get('resume_after_move'):job['resume_pending']=True
    save(jobs)
    resume_original(api,rows,jobs,job)


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
        if job.get('shared'):job['shared']['attempt']=uuid.uuid4().hex
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
