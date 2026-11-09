"""Use the conversion workflow's original-file and seeding choices for merges."""
import download_storage as storage
import library_conversion as library


def prepare(sources, data):
    from qbit_rpc import share_policy
    result, torrents = {}, {}
    for key, (item, _, _, _) in zip(('base', 'donor'), sources):
        choice = data[key].get('original')
        row = item.get('_row')
        # Requests from previous clients retain the existing seeding policy.
        if choice is None:
            result[key] = {'hash':row['hash']} if row else {'disposition':'archive'}
            continue
        if not isinstance(choice, dict): raise ValueError('Vælg håndtering af originalfilen.')
        if row:
            if set(choice) != {'policy'} or not isinstance(choice['policy'], dict):
                raise ValueError('Torrentoriginaler skal håndteres med seeding og oprydning.')
            policy = share_policy(choice['policy'], manual=True)
            if policy['ratio_limit'] < 1: raise ValueError('Målratio skal være mindst 1.')
            if row['hash'] in torrents and torrents[row['hash']] != policy:
                raise ValueError('Filer i samme torrent skal have samme seedingvalg.')
            torrents[row['hash']] = policy
            result[key] = {'hash':row['hash'], 'policy':policy}
        else:
            if set(choice) != {'disposition'} or choice['disposition'] not in ('archive', 'delete'):
                raise ValueError('Vælg Originals eller sletning efter kontrol for filer uden torrent.')
            result[key] = {'disposition':choice['disposition']}
    return result


def apply(api, ident):
    from green_credit import CreditLedger
    from qbit_rpc import apply_limits
    # Match the supervisor's credit -> storage lock order. pending() prevents
    # original cleanup until every source has moved and these choices are saved.
    with CreditLedger().transaction() as credit:
        jobs = storage.read(library.ledger(), {})
        job = jobs[ident]
        if job.get('source_policies_applied'): return
        policies = {s['hash']:s['policy'] for s in job['source_options'].values() if s.get('policy')}
        rows = {r['hash']:r for r in api('torrents/info').json()}
        if not policies.keys() <= rows.keys():
            raise ValueError('En originaltorrent mangler. Seedingvalget kræver kontrol.')
        for hashed, policy in policies.items():
            row = rows[hashed]; credit.update(row)
            entry = credit.entries[hashed]
            entry.update(target=max(1,policy['ratio_limit']), ratio_only=policy['ratio_action']=='delete_ratio',
                         adaptive_seeding=policy['ratio_action']=='automatic',
                         stop_on_complete=policy['ratio_action']=='stop_keep', seed_minutes=policy.get('seed_minutes'))
            if policy['ratio_action'] != 'automatic': entry.pop('upload_potential', None)
            credit.save()
            action = 'Stop' if policy['ratio_action'] in ('keep','stop_keep') else 'RemoveWithContent'
            apply_limits(api, row, action=action)
        with storage.transaction():
            jobs = storage.read(library.ledger(), {})
            jobs[ident]['source_policies_applied'] = True
            library.save(jobs)
