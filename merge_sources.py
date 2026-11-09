"""Recoverable donor relocation after the merged result is durably published."""
import json
import os
from pathlib import Path
import time

import download_storage as storage
import library_conversion as library
from state import atomic


def plan(api, sources, ident, output):
    from merge_publish import plan as source_plan
    # Reuse the main source's full-torrent, ownership and collision checks.
    donor = source_plan(api, [sources[1]], ident, output)
    donor.pop('created_at')
    donor['phase'] = 'pending'
    donor['stage'] = str(storage.buffer_root()/storage.BUFFER/('merge-donor-'+ident))
    if not donor.get('manual') and not donor.get('reuse_seeding'):
        name = storage.download_name(sources[1][0]['_row'].get('name', 'Film'))[:100]
        donor['seed'] = str(storage.seeding_root()/(name+'-'+ident[:8]+'-donor'))
    if donor.get('hash') and donor['hash'] == (sources[0][0].get('_row') or {}).get('hash'):
        donor['shared_main_torrent'] = True
    elif not donor.get('manual'):
        # Moving a multi-film donor torrent would remove unrelated library films.
        if any(f['name'] != donor['selected'] and Path(f['name']).suffix.lower() in library.VIDEO
               for f in donor['files']):
            raise ValueError('Filen med ekstra spor deler torrent med andre film. Vælg en donorfil uden andre film i samme torrent.')
    return donor


def result(parent):
    target = library.checked(parent['destination'] if parent.get('manual') else
                             Path(parent['original'])/parent['output'])
    flag = storage.read(library.marker(target), {})
    if (flag.get('id') != parent['id'] or not target.is_file() or
            library.fingerprint(target) != parent.get('published_result', parent.get('verified_result'))):
        raise ValueError('Den flettede fil mangler eller er ændret. Donorfilen er bevaret.')


def unowned(api, paths, own_hash=None):
    for row in api('torrents/info').json():
        if row['hash'] != own_hash and storage.managed_directory(row.get('save_path', '')):
            if any(str(Path(row['save_path'])/f['name']) in paths for f in library.selected_files(api, row)):
                raise ValueError('En anden torrent bruger kildefilerne. Flytningen er sat på pause.')


def advance(api, ident):
    """Persist each move before requesting it; never remux on cleanup retries."""
    jobs = storage.read(library.ledger(), {})
    parent = jobs[ident]; donor = parent['donor_cleanup']
    result(parent)
    if donor.get('done'): return True
    if donor.get('manual'):
        return archive(api, ident)
    with storage.transaction() as entries:
        jobs = storage.read(library.ledger(), {})
        parent = jobs[ident]; donor = parent['donor_cleanup']
        result(parent)
        rows = api('torrents/info').json()
        row = next((r for r in rows if r['hash'] == donor['hash']), None)
        if not row: raise ValueError('Donorens torrent mangler. Dens placering kræver kontrol.')
        if donor.get('shared_main_torrent'):
            donor['seed'] = parent['seed']
            donor['phase'] = 'moving'
        seed, original = library.checked(donor['seed']), library.checked(donor['original'])
        current = str(row.get('save_path', '')).rstrip('/')
        if donor['phase'] == 'pending':
            library.verify_sources(donor, seed if donor.get('reuse_seeding') else original)
            paths = {str(original/f['name']) for f in donor['files']}
            unowned(api, paths, donor['hash'])
            if current not in (str(original), str(seed)):
                raise ValueError('Donorens placering er ændret. Ingen filer flyttes.')
            if row.get('progress') != 1 or row.get('state') not in library.STABLE: return False
            if current != str(seed) and seed.exists() and any(seed.iterdir()):
                raise ValueError('Donorens seedingmappe indeholder allerede filer.')
            donor.setdefault('resume_after_move', row.get('state') in ('uploading','stalledUP','forcedUP','queuedUP'))
            donor['phase'] = 'moving'; library.save(jobs)
        if current == str(original):
            library.verify_sources(donor, original)
            unowned(api, {str(original/f['name']) for f in donor['files']}, donor['hash'])
            if time.time()-donor.get('move_requested_at', 0) > 30:
                seed.mkdir(parents=True, exist_ok=True)
                donor['move_requested_at'] = time.time(); library.save(jobs)
                api('torrents/stop', {'hashes': donor['hash']})
                if row.get('auto_tmm'):
                    api('torrents/setAutoManagement', {'hashes': donor['hash'], 'enable': 'false'})
                api('torrents/setLocation', {'hashes': donor['hash'], 'location': str(seed)})
            return False
        if current != str(seed): raise ValueError('Donorens placering er ændret under flytningen.')
        if row.get('progress') != 1 or row.get('state') not in library.STABLE: return False
        verified = library.verify_moved_sources(api, donor, seed)
        library.save(jobs)
        if not verified: return False
        # Existing seeded copies and a donor sharing the main torrent leave a
        # library copy. Only remove that exact, unchanged selected donor file.
        old = library.checked(donor['source'])
        if old.exists():
            if library.fingerprint(old) != donor['source_fingerprint']:
                raise ValueError('Donorens bibliotekskopi er ændret. Den er bevaret.')
            unowned(api, {str(old)})
            result(parent)
            old.unlink()
        for field in ('hash','infohash_v1','infohash_v2'):
            key = row.get(field)
            if key:
                entries[key] = {**entries.get(key, {}), 'stage':str(seed), 'target':str(original),
                                'published':True, 'library_replaced':True}
        atomic(storage.CONFIG/'download-storage.json', json.dumps(entries))
        if donor.get('resume_after_move'):
            donor['resume_pending'] = True; library.save(jobs)
            library.resume_original(api, rows, jobs, donor)
            if donor.get('resume_pending'): return False
        donor['done'] = True; library.save(jobs)
        return True


def archive(api, ident):
    # The merge worker lock serializes recovery. Large copies and checksums run
    # outside the storage transaction so the rest of the application can respond.
    jobs = storage.read(library.ledger(), {})
    parent = jobs[ident]; donor = parent['donor_cleanup']
    source, target = library.checked(donor['source']), library.checked(donor['archive'])
    if source.exists():
        if library.fingerprint(source) != donor['source_fingerprint']:
            raise ValueError('Donorfilen er ændret. Den er bevaret.')
        unowned(api, {str(source)})
        target.parent.mkdir(parents=True, exist_ok=True)
        library.publish_file(donor, source, target)
        if (not os.path.samefile(source, target) and library.file_digest(source) != library.file_digest(target)):
            raise ValueError('Donorens kopi i Originals matcher ikke. Kilden er bevaret.')
    elif not donor.get('archived_fingerprint'):
        raise ValueError('Donorens placering kunne ikke bekræftes.')
    with storage.transaction():
        jobs = storage.read(library.ledger(), {})
        parent = jobs[ident]; donor = parent['donor_cleanup']
        result(parent)
        if source.exists():
            if library.fingerprint(source) != donor['source_fingerprint']:
                raise ValueError('Donorfilen ændrede sig under arkiveringen.')
            unowned(api, {str(source)})
            donor['archived_fingerprint'] = library.fingerprint(target); library.save(jobs)
            source.unlink()
        if library.fingerprint(target) != donor['archived_fingerprint']:
            raise ValueError('Donorens arkivkopi er ændret.')
        library.scratch(donor, target).unlink(missing_ok=True)
        donor['done'] = True; library.save(jobs)
    return True
