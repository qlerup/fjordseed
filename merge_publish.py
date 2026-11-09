"""Hand a verified remux to the existing recoverable library publisher."""
import json
import os
from pathlib import Path
import shutil
import time

import download_storage as storage
import library_conversion as library
from state import atomic


def plan(api, sources, ident, output):
    item, source, _, _ = sources[0]
    root = library.checked(storage.download_root())
    if not source.is_relative_to(root): raise ValueError('Hovedfilen ligger uden for biblioteket.')
    row = item.get('_row')
    stage = library.checked(storage.buffer_root()/storage.BUFFER/('merge-'+ident))
    job = {'id': ident, 'merge_id': ident, 'root': str(root), 'source': str(source),
           'stage': str(stage), 'bitrate': 0, 'conversion_mode': 'merge', 'options': {'mode':'merge'},
           'phase': 'preparing', 'created_at': time.time(), 'source_fingerprint': library.fingerprint(source)}
    if not row:
        archive = library.checked(storage.originals_root()/source.relative_to(root))
        if archive.exists(): archive = archive.with_name(archive.stem+'-'+ident[:8]+archive.suffix)
        job.update(manual=True, hash=None, original=str(source.parent), selected=source.name,
                   output=output, destination=str(source.with_name(output)),
                   files=[{'name':source.name, 'size':source.stat().st_size, 'fingerprint':library.fingerprint(source)}],
                   options={'mode':'merge'}, original_disposition='archive', archive=str(archive))
        return job
    prior = item.get('_prior')
    torrent_base = library.checked(Path(row['save_path']))
    original = library.checked(Path(prior['original'])) if prior else torrent_base
    files = []
    # qBittorrent moves the entire torrent, including skipped companion files.
    for entry in api('torrents/files?hash='+row['hash']).json():
        name = str(library.safe_relative(entry['name']))
        path = library.checked(torrent_base/name)
        if not path.is_file() or path.stat().st_size != entry['size']:
            raise ValueError('Hele hovedfilens torrent skal være hentet, før originalen kan flyttes.')
        files.append({'name':name, 'size':entry['size'], 'fingerprint':library.fingerprint(path)})
    selected = source.relative_to(original).as_posix()
    if selected not in {f['name'] for f in files}: raise ValueError('Hovedfilen matcher ikke torrentens filliste.')
    if any(j.get('hash') == row['hash'] and j['phase'] not in ('published','cancelled')
           for j in storage.read(library.ledger(), {}).values()):
        raise ValueError('Hovedfilens torrent har allerede et aktivt flytte- eller konverteringsjob.')
    if prior and library.fingerprint(source) != next(f['fingerprint'] for f in files if f['name']==selected):
        raise ValueError('Bibliotekets original matcher ikke den seedende fil.')
    if not original.is_relative_to(root): raise ValueError('Hovedfilens torrent ligger uden for biblioteket.')
    seed = torrent_base if prior else storage.seeding_root()/(storage.download_name(row.get('name','Film'))[:100]+'-'+ident[:8])
    job.update(hash=row['hash'], original=str(original), selected=selected,
               output=str(Path(selected).with_name(output)), files=files, seed=str(seed))
    if prior: job['reuse_seeding'] = True
    return job


def handoff(api, sources, merge_job, result):
    """Prepare outside the storage lock; commit the ready receipt and job together."""
    ident = merge_job['id']
    prior = storage.read(library.ledger(), {}).get(ident)
    if prior:
        if prior.get('merge_id') != ident: raise ValueError('Et andet job bruger fletningens id.')
        return
    job = plan(api, sources, ident, merge_job['output'])
    stage = library.checked(job['stage']); stage.mkdir(parents=True, exist_ok=True)
    # Only companions need copies. The selected original will be moved by qBittorrent.
    if not job.get('manual'):
        base = Path(job['seed'] if job.get('reuse_seeding') else job['original'])
        for entry in job['files']:
            if entry['name'] == job['selected']: continue
            source = library.checked(base/entry['name']); target = library.checked(stage/entry['name'])
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                if source.suffix.lower() in library.VIDEO: library.snapshot(source, target)
                else: shutil.copy2(source, target)
            if library.fingerprint(target) != entry['fingerprint']:
                raise ValueError('En ledsagefil er ændret. Originalen flyttes ikke.')
    work = library.checked(stage/library.DIRECTORY)
    destination = library.checked(work/'result'/job['output'])
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and library.fingerprint(destination) != library.fingerprint(result):
        destination.unlink()  # Disposable work copy from an interrupted handoff.
    if not destination.exists(): library.snapshot(result, destination)
    if library.fingerprint(destination) != library.fingerprint(result):
        raise ValueError('Arbejdskopien af fletningen er ændret. Originalen flyttes ikke.')
    with destination.open('rb+') as handle: os.fsync(handle.fileno())
    job['verified_result'] = library.fingerprint(destination)
    with storage.transaction():
        import merge_media
        current_sources, _ = merge_media.validate(api, merge_job)
        # Recheck ownership and all torrent fingerprints after any large copies.
        current = plan(api, current_sources, ident, merge_job['output'])
        if any(current.get(k) != job.get(k) for k in ('files','hash','original','source_fingerprint')):
            raise ValueError('Hovedfilen eller torrenten er ændret under klargøringen.')
        atomic(work/'result'/'.fjordseed-converted.json', json.dumps({'id':ident,'files':[job['output']]}), mode=0o644)
        atomic(work/'status.json', json.dumps({'id':ident,'state':'ready','progress':100}), mode=0o644)
        job['phase'] = 'queued'
        jobs = storage.read(library.ledger(), {}); jobs[ident] = job; library.save(jobs)


def advance(api, ident):
    """Use the same move verification, publication and resume logic as conversion."""
    jobs = storage.read(library.ledger(), {}); job = jobs[ident]
    if job.get('manual'):
        if job.get('result_verify_required'): library.verify_manual_result(job)
        if job.get('archive_copy_required'): library.archive_manual_original(job)
    rows = api('torrents/info').json()
    with storage.transaction() as entries:
        jobs = storage.read(library.ledger(), {}); job = jobs[ident]
        try:
            library.advance(api, rows, entries, jobs, job)
            job.pop('error', None)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            job['error'] = str(exc)
            raise
        finally: library.save(jobs)
        done = job['phase']=='published' and not any(job.get(k) for k in
            ('original_pending','result_verify_required','resume_pending'))
        return done, ('originalen er gemt i Originals' if job.get('manual') else 'originalen ligger i Seeder')
