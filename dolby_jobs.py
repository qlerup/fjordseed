"""Persistent DV restoration jobs; executes inside the scoped storage container."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import download_storage as storage
from state import atomic
import dolby_backup as backup


def ledger():return storage.CONFIG/'dolby-vision.json'


@contextlib.contextmanager
def locked():
    storage.CONFIG.mkdir(parents=True,exist_ok=True)
    with backup.checked(storage.CONFIG/'dolby-vision.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        jobs=storage.read(ledger(),{})
        yield jobs
        atomic(ledger(),json.dumps(jobs))


def roots():
    result=[backup.checked(storage.download_root())]
    base=Path('/download-locations')
    if base.exists():
        import re
        result += [backup.checked(p) for p in base.iterdir() if re.fullmatch('[a-f0-9]{32}',p.name) and not p.is_symlink()]
    return list(dict.fromkeys(result))


def allowed(path):
    path=backup.checked(path)
    if not any(path.is_relative_to(root) for root in roots()):
        raise ValueError('Filen ligger ikke længere på et tilsluttet bibliotek.')
    if any(part.startswith('.') or part in ('Seeder','seedingmappe') for part in path.parts):
        raise ValueError('Gendannelse er kun tilladt i det publicerede bibliotek.')
    return path


def public(job):
    return {k:job.get(k) for k in ('id','name','state','detail','created_at','restored_at','archive_size')}


def discover():
    found=[];visited=0;truncated=False
    for root in roots():
        for folder,dirs,names in os.walk(root,followlinks=False):
            dirs[:]=sorted(d for d in dirs if not d.startswith('.') and d not in ('Seeder','seedingmappe') and not (Path(folder)/d).is_symlink())
            for name in sorted(names):
                visited+=1
                if visited>100000 or len(found)>=5000:truncated=True;break
                if not name.endswith(backup.SUFFIX):continue
                archive=backup.checked(Path(folder)/name)
                path=allowed(Path(str(archive)[:-len(backup.SUFFIX)]))
                if not path.is_file():continue
                ident=hashlib.sha256(str(path).encode()).hexdigest()
                try:
                    m=backup.metadata(archive)
                    found.append({'id':ident,'path':str(path),'name':path.relative_to(root).as_posix(),
                                  'created_at':m['created_at'],'archive_size':archive.stat().st_size,
                                  'state':'available','detail':'HDR10 · Dolby Vision er gemt'})
                except (OSError,ValueError,KeyError,backup.zipfile.BadZipFile):
                    found.append({'id':ident,'path':str(path),'name':path.relative_to(root).as_posix(),
                                  'state':'error','detail':'Dolby Vision-arkivet kunne ikke læses.'})
            if truncated:break
        if truncated:break
    with locked() as jobs:
        for item in found:
            if item['id'] not in jobs:jobs[item['id']]=item
        result=[public(j) for j in jobs.values()]
    return {'items':sorted(result,key=lambda j:j['name'].casefold()),'truncated':truncated}


def kick():
    # Detached from the short-lived RPC. A process lock serializes all restores.
    subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'run'],
                     stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)


def listing():
    result=discover()
    if any(j['state'] in ('queued','restoring') for j in result['items']):kick()
    return result


def queue(ident):
    with locked() as jobs:
        job=jobs.get(ident)
        if not job:raise ValueError('Dolby Vision-konverteringen findes ikke.')
        allowed(job['path'])
        if job['state'] not in ('restored','queued','restoring'):
            job.update(state='queued',detail='Venter på gendannelse · HDR10-filen bevares indtil kontrollen er færdig')
        result=public(job)
    kick()
    return result


def run():
    with backup.checked(storage.CONFIG/'dolby-vision-worker.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        while True:
            with locked() as jobs:
                job=next((dict(j) for j in jobs.values() if j['state'] in ('queued','restoring')),None)
                if not job:return
                jobs[job['id']].update(state='restoring',detail='Kontrollerer og gendanner Dolby Vision · ingen ny billedkomprimering')
            try:
                path=allowed(job['path'])
                # Only leftovers for this exact path, under the worker lock.
                prefix='.fjord-dv-restore-'+hashlib.sha256(str(path).encode()).hexdigest()[:16]+'-'
                for temporary in path.parent.glob(prefix+'*.mkv'):
                    backup.checked(temporary).unlink()
                backup.restore(path)
                result={'state':'restored','detail':'Dolby Vision 8.1 gendannet og kontrolleret','restored_at':time.time()}
            except Exception as exc:
                result={'state':'error','detail':str(exc)[:300] or 'Gendannelse mislykkedes. Prøv igen.'}
            with locked() as jobs:jobs[job['id']].update(result)


if __name__=='__main__':run()
