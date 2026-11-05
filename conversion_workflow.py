"""Durable, sequential library review queue. Original media stays qBittorrent-owned."""
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

import download_storage as storage
import library_conversion as library
from conversion_options import MODES, normalize
from state import atomic


def ledger(): return storage.CONFIG/'conversion-workflow.json'

def read(): return storage.read(ledger(), {'jobs': [], 'skipped': {}})

def save(data): atomic(ledger(), json.dumps(data))


def media_info(path):
    stamp = library.fingerprint(path)
    cache = storage.CONFIG/'conversion-media'/ (library.key(path)+'.json')
    stored = storage.read(cache, {})
    if stored.get('fingerprint') == stamp: return stored['media']
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-show_chapters',
                             '-of', 'json', str(path)], capture_output=True, text=True, check=True, timeout=8)
    media = json.loads(result.stdout)
    if not any(s.get('codec_type') == 'video' for s in media.get('streams', [])):
        raise ValueError('Filen indeholder ikke et videospor.')
    cache.parent.mkdir(parents=True, exist_ok=True)
    atomic(cache, json.dumps({'fingerprint':stamp, 'media':media}))
    return media


def details(api, ident):
    # Reading one header does not require re-querying every torrent/owner. The
    # actual queue still validates ownership through the complete inventory.
    root = library.checked(storage.download_root())
    found = None
    seen = 0
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d not in ('Seeder', 'seedingmappe')
                         and not (Path(folder)/d).is_symlink())
        for name in sorted(names):
            path = Path(folder)/name
            if path.suffix.lower() not in library.VIDEO or path.is_symlink(): continue
            seen += 1
            if library.key(path) == ident:
                found = library.checked(path); break
        if found or seen >= 5000: break
    if not found: raise ValueError('Filmen findes ikke længere i biblioteket.')
    try: media = media_info(found)
    except (subprocess.SubprocessError, OSError, ValueError):
        raise ValueError('Medieoplysninger kunne ikke læses. Prøv igen; filmen er ikke ændret.') from None
    return {'media': media, 'fingerprint': library.fingerprint(found)}


def listing(api):
    result = library.inventory(api)
    state = read()
    for item in result['items']:
        row = item.pop('_row', None) or {}
        path = Path(item.pop('_path'))
        item.pop('_prior', None)
        item['hash'] = row.get('hash')
        item['title'] = row.get('name') or path.stem
        item['skipped_modes'] = [mode for mode, ids in state['skipped'].items() if item['id'] in ids]
        cache = storage.read(storage.CONFIG/'conversion-media'/(item['id']+'.json'), {})
        if cache.get('fingerprint') == library.fingerprint(path): item['media'] = cache['media']
    active = [j for j in state['jobs'] if j['state'] not in ('done', 'cancelled')]
    history = [j for j in state['jobs'] if j['state'] == 'done'][-20:]
    result['jobs'] = [{k:v for k,v in j.items() if k != 'fingerprint'} for j in active+history]
    return result


def skip(api, data):
    mode, ident = data.get('mode'), data.get('id')
    if mode not in MODES or type(data.get('skip')) is not bool: raise ValueError('Ugyldigt spring over-valg.')
    if ident not in {i['id'] for i in library.inventory(api)['items']}: raise ValueError('Filmen findes ikke.')
    with storage.transaction():
        state = read(); ids = set(state['skipped'].get(mode, []))
        if data['skip']: ids.add(ident)
        else: ids.discard(ident)
        state['skipped'][mode] = sorted(ids); save(state)
    return {'ok': True}


def enqueue(api, data):
    from qbit_rpc import share_policy
    choices = data.get('items')
    if not isinstance(choices, list) or not 1 <= len(choices) <= 100:
        raise ValueError('Vælg mellem 1 og 100 film.')
    # Probe before the commit; enqueue is all-or-nothing and creates no media files.
    inventory = {i['id']: i for i in library.inventory(api)['items']}
    prepared = []
    for choice in choices:
        if not isinstance(choice, dict): raise ValueError('Ugyldigt filmvalg.')
        item = inventory.get(choice.get('id'))
        if not item or not item['eligible']: raise ValueError((item or {}).get('reason') or 'Filmen findes ikke.')
        path = Path(item['_path'])
        options = normalize(choice.get('options'), media_info(path))
        if choice.get('fingerprint') != library.fingerprint(path): raise ValueError('Filmen er ændret. Genåbn filmvalget.')
        policy = share_policy(choice.get('policy', {}), manual=True)
        if policy['ratio_action'] not in ('keep', 'stop_keep') and policy['ratio_limit'] < 1:
            raise ValueError('Målratio skal være mindst 1.')
        prepared.append({'id': uuid.uuid4().hex, 'file_id': item['id'], 'hash': item['_row']['hash'],
                         'name': item['name'], 'options': options, 'policy': policy,
                         'fingerprint': library.fingerprint(path), 'state': 'queued', 'created_at': time.time()})
    with storage.transaction():
        state = read()
        if sum(j['state'] not in ('done', 'cancelled') for j in state['jobs']) + len(prepared) > 500:
            raise ValueError('Køen kan højst indeholde 500 ventende film.')
        hashes = {j['file_id'] for j in state['jobs'] if j['state'] not in ('done', 'cancelled')}
        policies = {j['hash']: j['policy'] for j in state['jobs'] if j['state'] not in ('done', 'cancelled')}
        for job in prepared:
            if job['hash'] in policies and policies[job['hash']] != job['policy']:
                raise ValueError('Film i samme torrent skal have samme seedingvalg. qBittorrent flytter og rydder op i hele torrenten.')
            policies[job['hash']] = job['policy']
            if job['file_id'] in hashes: raise ValueError('Filmen er allerede valgt eller i kø.')
            if job['file_id'] in state['skipped'].get(job['options']['mode'], []): raise ValueError('Filmen er sprunget over. Gendan den først.')
            hashes.add(job['file_id'])
        state['jobs'].extend(prepared); save(state)
    return {'ok': True, 'jobs': [j['id'] for j in prepared]}


def pending(ident):
    return any(j['hash'] == ident and j['state'] not in ('done', 'cancelled') for j in read()['jobs'])


def cancel(ident):
    with storage.transaction():
        state = read(); job = next((j for j in state['jobs'] if j['id'] == ident), None)
        if not job or job['state'] not in ('queued', 'error') or job.get('library_id'):
            raise ValueError('Kun ventende film kan fjernes fra køen.')
        job['state'] = 'cancelled'; save(state)
    return {'ok': True}


def tick(api, rows, credit=None):
    """Prepare on the maintenance RPC, outside VPN supervision and credit locks."""
    state = read()
    job = next((j for j in state['jobs'] if j['state'] not in ('done', 'cancelled')), None)
    if not job: return
    try:
        jobs = storage.read(library.ledger(), {})
        # Recover a crash between queue creation and recording its returned ID.
        current = jobs.get(job.get('library_id')) or next((j for j in jobs.values() if
            j.get('workflow_id') == job['id']), None)
        if current:
            job['library_id'] = current['id']; job['state'] = 'running'
            if current.get('phase') == 'preparing':
                library.prepare_review_job(current, Path(current['seed'] if current.get('reuse_seeding') else current['original']))
                current = storage.read(library.ledger(), {})[current['id']]
            public = library.public_job(current)
            job.update(progress=public['progress'], detail=public['detail'], phase=public['state'])
            if current.get('phase') == 'published':
                if credit is None:
                    from green_credit import CreditLedger
                    with CreditLedger().transaction() as locked_credit:
                        return tick(api, rows, locked_credit)
                row = next((r for r in rows if r['hash'] == job['hash']), None)
                if not row: raise ValueError('Originalens torrent mangler efter flytningen.')
                from qbit_rpc import apply_limits
                policy = job['policy']; credit.update(row)
                entry = credit.entries[job['hash']]
                entry.update(target=max(1,policy['ratio_limit']), ratio_only=policy['ratio_action']=='delete_ratio',
                    adaptive_seeding=policy['ratio_action']=='automatic', stop_on_complete=policy['ratio_action']=='stop_keep',
                    seed_minutes=policy.get('seed_minutes'))
                credit.save()
                action = 'Stop' if policy['ratio_action'] in ('keep','stop_keep') else 'RemoveWithContent'
                apply_limits(api,row,action=action)
                row['share_limit_action'] = action
                job.update(state='done', phase='published', progress=100, detail='Færdig · originalen ligger i Seeder')
            elif current.get('phase') == 'cancelled': job['state'] = 'cancelled'
            elif public['state'] == 'error': job['state'] = 'error'
        elif job['state'] in ('queued', 'starting'):
            # This queue waits for any earlier library work before starting.
            if any(j['phase'] not in ('published','cancelled') for j in jobs.values()): return
            item = next((i for i in library.inventory(api)['items'] if i['id'] == job['file_id']), None)
            if not item or library.fingerprint(Path(item['_path'])) != job['fingerprint']:
                raise ValueError('Filmen er ændret efter dit valg. Originalen er bevaret.')
            with storage.transaction():
                latest = read()
                live = next(j for j in latest['jobs'] if j['id'] == job['id'])
                if live['state'] not in ('queued', 'starting'): return
                live['state'] = 'starting'; save(latest)
            result = library.queue(api, job['file_id'], job['options']['bitrate'], options=job['options'], workflow_id=job['id'])
            job.update(library_id=result['id'], state='running')
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        linked = next((j for j in storage.read(library.ledger(), {}).values() if j.get('workflow_id') == job['id']), None)
        if linked: job['library_id'] = linked['id']
        job.update(state='error', detail=str(exc))
    # Merge this job only: skip/enqueue actions may have occurred while probing.
    with storage.transaction():
        latest = read()
        for i, other in enumerate(latest['jobs']):
            if other['id'] == job['id']: latest['jobs'][i] = job
        save(latest)


def retry(ident):
    state = read(); job = next((j for j in state['jobs'] if j['id'] == ident), None)
    if not job or job['state'] != 'error': raise ValueError('Jobbet er ikke fejlet.')
    if job.get('library_id'):
        current = storage.read(library.ledger(), {}).get(job['library_id'], {})
        if current.get('phase') == 'queued': library.retry(job['library_id'])
    with storage.transaction():
        state = read(); job = next(j for j in state['jobs'] if j['id'] == ident)
        job.update(state='running' if job.get('library_id') else 'queued', detail=''); save(state)
    return {'ok':True}
