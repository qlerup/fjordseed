"""Durable filesystem hand-off to the GPU worker; torrents retain their originals."""
import json
import math
import os
import subprocess
from pathlib import Path, PurePosixPath
import time
import uuid

from state import atomic

DIRECTORY = '.fjordseed-conversion'
HEARTBEAT = '.fjordseed-converter.json'


def choice(value):
    if type(value) is not bool:
        raise ValueError('Vælg om download skal konverteres.')
    return value


def available(root,target='server'):
    try:
        heartbeat='.fjordseed-remote.json' if target=='pc' else HEARTBEAT
        data = json.loads((Path(root)/'.incomplete'/heartbeat).read_text())
        return data.get('version') == 1 and 0 <= time.time()-data['at'] < 45
    except (OSError, ValueError, TypeError, KeyError):
        return False


def require_enabled():
    from download_storage import read, SETTINGS, download_root
    if not read(SETTINGS, {}).get('conversion_enabled', False):
        raise ValueError('Slå GPU-konvertering til under Indstillinger → Konvertering først.')
    if not available(download_root(),read(SETTINGS,{}).get('conversion_target','server')):
        raise ValueError('GPU-konverteren er ikke klar til den valgte buffer. Download afventer.')


def safe_relative(name):
    if (not isinstance(name, str) or not name or len(name)>4096 or '\\' in name
            or any(ord(c)<32 for c in name)):
        raise ValueError('Ugyldigt filnavn i konverteringsjob.')
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or str(path)!=name or any(p.startswith('.fjordseed') for p in path.parts):
        raise ValueError('Ugyldig sti i konverteringsjob.')
    return path


def checked(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Konvertering må ikke følge symbolske links.')
    return path


def status(record):
    if record.get('published'):
        return {'state':'published', 'progress':100, 'detail':'Beholdt uændret · bitrate under grænsen' if record.get('bitrate_skipped') else 'Konverteret fil i biblioteket · originalen seeder i bufferen'}
    try:
        data = json.loads(checked(Path(record['stage'])/DIRECTORY/'status.json').read_text())
        if data.get('id') != record.get('conversion_id'):
            raise ValueError()
        return {key:data[key] for key in ('state','progress','detail','stage','stage_started_at','at') if key in data}
    except (OSError, ValueError, TypeError):
        return {'state':'queued' if record.get('conversion_id') else 'downloading', 'progress':0,
                'detail':'Venter på GPU-konvertering' if record.get('conversion_id') else 'Downloader originalen til bufferen'}


def bitrate_decisions(files,stage,bitrate):
    """Only automatic opt-in downloads use the source's total bitrate + 5%."""
    from media_bitrates import probe
    from converter_worker import VIDEO
    result=[]
    for entry in files:
        entry=dict(entry)
        if Path(entry['name']).suffix.lower() in VIDEO:
            try:total=probe(checked(Path(stage)/entry['name'])).get('total_bps')
            except (OSError,subprocess.SubprocessError) as exc:
                raise ValueError('Samlet bitrate kunne ikke måles. Automatisk konvertering afventer.') from exc
            if type(total) not in (int,float) or not math.isfinite(total) or total<=0:
                raise ValueError('Samlet bitrate kunne ikke måles. Automatisk konvertering afventer.')
            entry.update(input_total_bps=total,convert=total>bitrate*1_050_000)
        result.append(entry)
    return result


def reconcile(api, row, record):
    """Called under storage lock. Never change qBittorrent's save path."""
    if record.get('published') or row.get('progress') != 1 or row.get('state') not in {
            'uploading','stalledUP','forcedUP','stoppedUP','pausedUP','queuedUP'}:
        return
    stage = checked(record['stage'])
    if str(row.get('save_path','')).rstrip('/') != str(stage):
        raise ValueError('Originalens placering er ændret; konvertering er sat på pause.')
    work = checked(stage/DIRECTORY)
    if not record.get('conversion_id'):
        files = api('torrents/files?hash='+row['hash']).json()
        if not isinstance(files,list) or not 1<=len(files)<=10000:
            raise ValueError('Torrentens filliste kunne ikke kontrolleres.')
        names=[]
        for file in files:
            if file.get('priority',1)==0:
                continue
            name=str(safe_relative(file.get('name')))
            source=checked(stage/name)
            if not source.is_file() or source.stat().st_size != file.get('size'):
                raise ValueError('En kildefil er ikke færdig endnu.')
            names.append({'name':name,'size':file['size']})
        if not names:
            raise ValueError('Ingen valgte filer til konvertering.')
        work.mkdir(exist_ok=True)
        # Reuse intent across a crash between request creation and ledger save.
        request_path=checked(work/'request.json')
        if request_path.exists():
            request=json.loads(request_path.read_text())
            if [{k:f[k] for k in ('name','size')} for f in request.get('files',[])]!=names or request.get('bitrate')!=record['conversion_bitrate']:
                raise ValueError('Konverteringsjobbet matcher ikke længere torrenten.')
        else:
            if record.get('conversion_bitrate_margin')==5:
                names=bitrate_decisions(names,stage,record['conversion_bitrate'])
            request={'version':1,'id':uuid.uuid4().hex,'files':names,'bitrate':record['conversion_bitrate'],
                     'executor':record.get('conversion_target','server')}
            if any(f.get('convert') is not False and Path(f['name']).suffix.lower() in {'.mkv','.mp4','.m4v','.avi','.mov','.ts','.m2ts','.webm'} for f in names):
                atomic(request_path,json.dumps(request),mode=0o644)
        record['conversion_id']=request['id']
        if names and all(entry.get('convert') is False or Path(entry['name']).suffix.lower() not in {'.mkv','.mp4','.m4v','.avi','.mov','.ts','.m2ts','.webm'} for entry in request['files']):
            # No GPU is required when every video already satisfies the limit.
            result=checked(work/'result');result.mkdir(exist_ok=True)
            for entry in request['files']:
                source=checked(stage/entry['name']);target=checked(result/entry['name'])
                target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists():os.link(source,target)
                elif not os.path.samefile(source,target):raise ValueError('En anden fil findes på bibliotekets arbejdsplads.')
            atomic(result/'.fjordseed-converted.json',json.dumps({'id':request['id'],'files':[e['name'] for e in request['files']],'bitrate_skipped':True}),mode=0o644)
            atomic(work/'status.json',json.dumps({'id':request['id'],'state':'ready','progress':100,'detail':'Beholdt uden konvertering · samlet bitrate er højst valgt bitrate + 5 %'}),mode=0o644)
            record['bitrate_skipped']=True
    result=status(record)
    if result.get('state')!='ready':
        return
    target=checked(record['target'])
    output=checked(work/'result')
    receipt_name='.fjordseed-converted.json'
    receipt=output/receipt_name if output.is_dir() else target/receipt_name
    data=json.loads(checked(receipt).read_text())
    if data.get('id')!=record['conversion_id']:
        raise ValueError('Konverteringskvitteringen matcher ikke download.')
    if output.is_dir():
        if target.exists():
            raise ValueError('Biblioteksmappen findes allerede; ingen filer overskrives.')
        target.parent.mkdir(parents=True,exist_ok=True)
        # Same filesystem: publish the complete, verified directory atomically.
        output.rename(target)
    record['published']=True


def finish(api,row,credit,record):
    """Exactly 1:1 OR 49 seed hours, but only after a verified library copy."""
    if not record.get('published') or row.get('progress')!=1:
        return False
    if str(row.get('save_path','')).rstrip('/') != record['stage']:
        return False  # Never delete library output after an external setLocation.
    from qbit_rpc import stop_requirement
    if not stop_requirement({**row,**credit})['seeding_requirement_met']:
        return False
    from deletion_events import delete_completed
    return delete_completed(api, row, credit, converted=True)


def retry(ident):
    import fcntl
    from download_storage import transaction
    with transaction() as entries:
        record=entries.get(ident,{})
        if not record.get('convert') or record.get('published'):
            raise ValueError('Der er ingen fejlet konvertering at genstarte.')
        work=checked(Path(record['stage'])/DIRECTORY)
        if not record.get('conversion_id'):
            record.pop('conversion_error',None)
            return
        with checked(work/'worker.lock').open('a') as handle:
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('Konverteringen kører allerede.') from None
            if status(record).get('state') not in ('error','waiting_space'):
                raise ValueError('Konverteringen er allerede i kø.')
            atomic(checked(work/'status.json'),json.dumps({'id':record['conversion_id'],'state':'queued',
                   'progress':0,'detail':'Venter på et nyt konverteringsforsøg'}),mode=0o644)
            record.pop('conversion_error',None)
