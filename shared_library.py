"""Shared-drive PC conversion; qBittorrent alone relocates original storage."""
import json
import hashlib
from pathlib import Path
import time

import library_conversion as library
import download_storage as storage
from conversion import DIRECTORY, checked, safe_relative
from state import atomic


def source_signature(path):
    size=Path(path).stat().st_size
    digest=hashlib.sha256(str(size).encode())
    with Path(path).open('rb') as handle:
        for offset in sorted({0,max(0,size//2-524288),max(0,size-1048576)}):
            handle.seek(offset);digest.update(str(offset).encode());digest.update(handle.read(1048576))
    return digest.hexdigest()


def command(job):
    shared=job['shared']
    result={**library.public_job(job),'action':'convert','attempt':shared['attempt'],
            'executor':shared.get('executor','pc'),
            'claimed':bool(shared.get('claimed_at')),
            'media_folder':shared['media_folder'],'name':shared['name'],
            'size':next(f['size'] for f in job['files'] if f['name']==job['selected']),
            'work':(Path(job['stage'])/DIRECTORY).relative_to(shared['server_root']).as_posix(),
            'output':job['output']}
    result['source_signature']=shared['source_signature']
    if job['phase']=='published':result.update(state='completed',progress=100,detail='Konverteret film i Bibliotek · originaltorrent i Seeder')
    elif job['phase']=='moving' and not job.get('error'):result.update(state='moving',detail='qBittorrent flytter hele originaltorrenten til Seeder')
    if job['phase']=='moving' and result.get('stage') in ('source_verifying','publishing') and not job.get('error'):
        result['detail']=library.public_job(job)['detail']
    result['stage']=result.get('stage') or {'completed':'completed','moving':'moving','ready':'waiting_move',
        'encoded':'server_verifying','verifying':'verifying','encoding':'encoding','queued':'queued','error':'error'}.get(result['state'],result['state'])
    if job['phase']=='published':result['stage']='completed'
    if job['phase']=='moving' and not job.get('error') and result.get('stage') not in ('source_verifying','publishing'):result['stage']='moving'
    if job.get('error'):result.update(state='error',stage='error',detail=job['error'])
    return result


def live_status(api,job):
    result=command(job)
    if job['phase']=='moving' and not job.get('error'):
        row=next((r for r in api('torrents/info').json() if r['hash']==job['hash']),None)
        if row:
            result.update(checked_at=time.time(),qbit_state=row.get('state'))
            if result['stage']=='moving':result['stage_started_at']=job.get('move_requested_at')
            if row.get('state')=='moving':
                from move_progress import estimate
                result.update(estimate(job))
            elif row.get('save_path','').rstrip('/')==job['seed'] and result.get('stage')!='source_verifying':
                result.update(stage='publishing',phase_progress=None,detail='Originalen er i Seeder · publicerer den kontrollerede film i biblioteket')
    return result


def owned(ident,device):
    job=storage.read(library.ledger(),{}).get(ident)
    if not job or job.get('shared',{}).get('device')!=device:raise ValueError('Jobbet tilhører ikke denne pc.')
    return job


def queue(api,data):
    executor=data.get('executor','pc')
    if executor not in ('pc','server'):raise ValueError('Ukendt konverteringsmaskine.')
    if type(data.get('bitrate')) is not int or data['bitrate'] not in (20,30,40):raise ValueError('Vælg 20, 30 eller 40 Mbps.')
    name=str(safe_relative(data.get('name')))
    with storage.transaction():
        jobs=storage.read(library.ledger(),{})
        previous=next((j for j in jobs.values() if j.get('shared',{}).get('device')==data.get('device') and
            j['shared']['media_folder']==data.get('media_folder') and j['shared']['name']==name and j['phase']=='queued'),None)
        if previous:
            if previous['shared'].get('executor','pc')!=executor:
                raise ValueError('Jobbet er allerede tildelt en anden maskine.')
            work=Path(previous['stage'])/DIRECTORY
            state=storage.read(work/'status.json',{})
            if state.get('state')!='error':
                if previous['bitrate']==data['bitrate']:return command(previous)
                raise ValueError('Filen har allerede et konverteringsjob med en anden bitrate.')
            if previous['bitrate']!=data['bitrate']:raise ValueError('Genstart jobbet med samme bitrate, eller afbryd det først.')
            library.verify_sources(previous,Path(previous['seed'] if previous.get('reuse_seeding') else previous['original']))
            import uuid
            previous['shared']['attempt']=uuid.uuid4().hex
            previous['bitrate']=data.get('bitrate');previous.pop('error',None)
            library.save(jobs)
            atomic(work/'status.json',json.dumps({'id':previous['id'],'state':'queued','progress':0}),mode=0o644)
            return command(previous)
    candidates=[i for i in library.inventory(api)['items']
                if i['size']==data.get('size') and (i['name']==name or i['name'].endswith('/'+name))]
    if len(candidates)!=1:raise ValueError('Pc-mappen kan ikke matches entydigt med serverens bibliotek.')
    item=candidates[0]
    server_root=Path(item['_path']).parents[len(Path(name).parts)-1]
    shared={'server_root':str(server_root),'media_folder':data['media_folder'],
            'name':name,'device':data['device'],'source_signature':source_signature(item['_path']),'executor':executor}
    queued=library.queue(api,item['id'],data.get('bitrate'),shared=shared)
    job=owned(queued['id'],data['device'])
    if executor=='server':
        fallback(api,job['id'],data['device'])
    return command(job)


def status(api,ident,device,claim=False):
    # The normal qBittorrent reconciliation performs moves and publication.
    job=owned(ident,device)
    if claim and (job['phase']!='queued' or job['shared'].get('claimed_at')):
        if job['shared'].get('executor','pc')!='pc':raise ValueError('Jobbet behandles af serverens GPU.')
        return live_status(api,job)  # Read-only polling must not wait on a large content check.
    if claim:
        with storage.transaction():
            jobs=storage.read(library.ledger(),{});job=owned(ident,device)
            if job['shared'].get('executor','pc')!='pc':raise ValueError('Jobbet behandles af serverens GPU.')
            if job['phase']=='queued' and not job['shared'].get('claimed_at'):
                job['shared']['claimed_at']=time.time();jobs[ident]=job;library.save(jobs)
            return live_status(api,job)
    return live_status(api,owned(ident,device))


def fallback(api,ident,device):
    """Atomic ownership handoff: a PC must claim before it can start encoding."""
    with storage.transaction():
        jobs=storage.read(library.ledger(),{});job=owned(ident,device)
        work=checked(Path(job['stage'])/DIRECTORY)
        state=storage.read(work/'status.json',{})
        if job['phase']!='queued' or job['shared'].get('claimed_at') or state.get('state')!='queued':
            raise ValueError('Et startet job kan ikke overtages af serveren.')
        stage=checked(job['stage']);source=checked(job['source']);target=checked(stage/job['selected'])
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():library.snapshot(source,target)
        if library.fingerprint(target)!=library.fingerprint(source):raise ValueError('Arbejdskopien matcher ikke originalen.')
        job['shared']['executor']='server';jobs[ident]=job;library.save(jobs)
        atomic(work/'request.json',json.dumps({'version':1,'id':ident,'executor':'server',
            'shared':True,'bitrate':job['bitrate'],'files':[{'name':job['selected'],'size':source.stat().st_size}]}),mode=0o644)
        return command(job)


def cancel(api,ident,device):
    job=owned(ident,device)
    if job['phase']=='cancelled':return command(job)
    library.cancel(ident)
    return command(owned(ident,device))


def failed(ident,device,detail):
    with storage.transaction():
        job=owned(ident,device)
        if job['phase']!='queued':return command(job)
        atomic(Path(job['stage'])/DIRECTORY/'status.json',json.dumps({'id':ident,'state':'error',
            'progress':0,'detail':str(detail)[:300]}),mode=0o644)
        return command(job)


def complete(api,ident,device):
    with storage.transaction():
        jobs=storage.read(library.ledger(),{})
        job=owned(ident,device)
        if job['phase'] in ('moving','published'):return command(job)
        if job['phase']!='queued':raise ValueError('Jobbet afventer ikke en pc-konvertering.')
        work=checked(Path(job['stage'])/DIRECTORY)
        state=storage.read(work/'status.json',{})
        if state.get('state')=='ready':return command(job)
        output=checked(work/'result'/job['output'])
        report=storage.read(checked(output.with_suffix('.json')), {})
        if (report.get('verified') is not True or report.get('video_mbps_target')!=job['bitrate'] or
                not str(report.get('gpu_encoder','')).startswith('NVEncC ')):
            raise ValueError('Den verificerede rapport fra pc’en mangler.')
        library.verify_sources(job,Path(job['seed'] if job.get('reuse_seeding') else job['original']))
        expected=next(f['fingerprint'] for f in job['files'] if f['name']==job['selected'])
        if library.fingerprint(job['source'])!=expected:raise ValueError('Bibliotekets kildefil er ændret.')
        before=library.fingerprint(output)
        atomic(work/'status.json',json.dumps({'id':ident,'state':'encoded','stage':'server_verifying',
            'stage_started_at':time.time(),'phase_progress':None,'progress':0,
            'detail':'Serveren kontrollerer video, lyd, undertekster, HDR og kapitler'}),mode=0o644)
        from conversion_media import probe,validate_file,prepare_output,dovi
        original=probe(job['source'])
        if dovi(original) and dovi(probe(output)):
            # Older Windows clients return DV; apply the same policy here.
            prepare_output(original,output)
            before=library.fingerprint(output)
        validate_file(original,output)
        if library.fingerprint(output)!=before:raise ValueError('Resultatet er ændret under kontrollen.')
        # Preserve loose companions even when not listed in the torrent.
        # Restrict discovery to torrent-owned subdirectories, never the whole library.
        import os,shutil
        current=Path(job['original']);stage=Path(job['stage'])
        top={Path(f['name']).parts[0] for f in job['files'] if len(Path(f['name']).parts)>1}
        roots=([current/name for name in top] or [Path(job['source']).parent]) if not job.get('reuse_seeding') else []
        tracked={f['name'] for f in job['files']};extras=[]
        for root in roots:
            for folder,dirs,names in os.walk(root,followlinks=False):
                dirs[:]=[d for d in dirs if not d.startswith('.') and not (Path(folder)/d).is_symlink()]
                for name in names:
                    path=Path(folder)/name
                    if name.startswith('.') or path.is_symlink() or path.suffix.lower() in library.VIDEO:continue
                    if root==storage.download_root() and not name.startswith(Path(job['source']).stem+'.'):continue
                    relative=path.relative_to(current).as_posix()
                    if relative in tracked or any(e['name']==relative for e in extras):continue
                    target=checked(stage/relative);target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(checked(path),target)
                    extras.append({'name':relative,'fingerprint':library.fingerprint(path)})
                if root==storage.download_root():dirs[:]=[]
        job['extras']=extras;job['verified_result']=before
        jobs[ident]=job;library.save(jobs)
        atomic(work/'result'/'.fjordseed-converted.json',json.dumps({'id':ident,'files':[job['output']]}),mode=0o644)
        atomic(work/'status.json',json.dumps({'id':ident,'state':'ready','progress':100,
            'stage':'waiting_move','stage_started_at':time.time(),'phase_progress':None,
            'detail':'Resultatet er kontrolleret · afventer flytning af originaltorrent'}),mode=0o644)
        return command(job)
