"""Filesystem broker, executed only inside a network-isolated buffer helper."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import uuid

from conversion import checked, safe_relative, DIRECTORY
from converter_worker import VIDEO, probe, validate, restore_flags, report
from state import atomic

CHUNK = 8 * 1024 * 1024
TTL = 180


def roots():
    return [checked(Path(p)) for p in os.environ['FJORDSEED_BUFFERS'].split(':')]


def requests():
    for root in roots():
        for path in sorted(root.glob('*/' + DIRECTORY + '/request.json')):
            checked(path)
            if path.stat().st_size > CHUNK:
                continue
            try:request = json.loads(path.read_text())
            except (ValueError,OSError):continue
            if not isinstance(request,dict):continue
            if request.get('executor', 'server') != 'pc':
                continue
            yield path.parent, request


@contextlib.contextmanager
def locked(work):
    with checked(work / 'worker.lock').open('a') as handle:
        deadline=time.monotonic()+5
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic()>=deadline:raise
                time.sleep(.025)
        yield


def read(path, default=None):
    try:
        return json.loads(checked(path).read_text())
    except FileNotFoundError:
        return default


def manifest(work, request):
    if not re.fullmatch('[a-f0-9]{32}', request.get('id', '')):
        raise ValueError('Ugyldigt job.')
    if request.get('version') != 1 or request.get('bitrate') not in (10,15,20,25,30):
        raise ValueError('Ugyldige konverteringsindstillinger.')
    files = request.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= 10000:
        raise ValueError('Ugyldig filliste.')
    result = []
    for index, entry in enumerate(files):
        name = str(safe_relative(entry['name']))
        source = checked(work.parent / name)
        if type(entry['size']) is not int or entry['size'] < 0 or not source.is_file() or source.stat().st_size != entry['size']:
            raise ValueError('Originalfilen mangler eller er ændret.')
        video = source.suffix.lower() in VIDEO
        result.append(dict(index=index, name=name, size=entry['size'], video=video,
                           output=str(Path(name).with_suffix('.mkv')) if video else name))
    if not any(f['video'] for f in result):
        raise ValueError('Ingen understøttede videofiler.')
    for key in ('name', 'output'):
        if len({f[key].casefold() for f in result}) != len(result):
            raise ValueError('Filnavne kolliderer.')
    return result


def lease_path(work):
    return checked(work / 'remote-lease.json')


def save_lease(work, lease):
    atomic(lease_path(work), json.dumps(lease), mode=0o600)


def job(data):
    ident = data.get('job', '')
    if not re.fullmatch('[a-f0-9]{32}', ident):
        raise ValueError('Ugyldigt job.')
    for work, request in requests():
        if request['id'] == ident:
            return work, request
    raise ValueError('Jobbet findes ikke længere.')


def authorize(work, data):
    lease = read(lease_path(work), {})
    if (lease.get('worker') != data.get('worker') or lease.get('lease') != data.get('lease')
            or lease.get('expires', 0) <= time.time()):
        raise ValueError('Jobreservationen er udløbet. Hent jobbet igen.')
    return lease


def private(work, lease):
    return checked(work / 'remote' / lease['lease'])


def file_info(work, request, data):
    files = manifest(work, request)
    index = data.get('index')
    if type(index) is not int or not 0 <= index < len(files):
        raise ValueError('Ugyldig fil.')
    return files[index]


def uploaded(work, lease, index):
    return checked(private(work, lease) / 'files' / str(index))


def digest(path):
    h = hashlib.sha256()
    with checked(path).open('rb') as handle:
        for block in iter(lambda: handle.read(CHUNK), b''):
            h.update(block)
    return h.hexdigest()


def dispatch(data):
    action = data['action']
    if action == 'heartbeat':
        for root in roots():
            atomic(checked(root / '.fjordseed-remote.json'), json.dumps({'version':1,'at':time.time()}), mode=0o644)
        return {'ready':True}
    if action == 'claim':
        for work, request in requests():
            try:
                with locked(work):
                    state = read(work / 'status.json', {})
                    if state.get('state') in ('ready', 'error'):
                        continue
                    previous = read(lease_path(work), {})
                    if previous.get('expires', 0) > time.time() and previous.get('worker') != data['worker']:
                        continue
                    files = manifest(work, request)
                    resume=previous.get('worker')==data['worker'] and previous.get('expires',0)>time.time()
                    if not resume and shutil.disk_usage(work).free<sum(f['size'] for f in files)+1024**3:
                        report(work,request['id'],'waiting_space','Venter på plads til den returnerede fil fra pc’en')
                        continue
                    lease = previous if resume else {
                        'worker':data['worker'], 'lease':uuid.uuid4().hex, 'done':{}}
                    lease['expires'] = time.time() + TTL
                    folder = private(work, lease)
                    checked(folder / 'incoming').mkdir(parents=True, exist_ok=True)
                    checked(folder / 'files').mkdir(exist_ok=True)
                    save_lease(work, lease)
                    report(work,request['id'],'remote','Reserveret til pc-konvertering',0)
                    for f in files:
                        target = uploaded(work, lease, f['index'])
                        f['uploaded'] = target.stat().st_size if target.exists() else 0
                        f['verified'] = str(f['index']) in lease['done']
                    return dict(id=request['id'], lease=lease['lease'], bitrate=request['bitrate'], files=files)
            except BlockingIOError:
                continue
            except ValueError as exc:
                if re.fullmatch('[a-f0-9]{32}',request.get('id','')):
                    report(work,request['id'],'error',str(exc))
                continue
        return None
    work, request = job(data)
    if action == 'verify':
        # Expensive probing does not block lease renewal or another HTTP thread.
        with locked(work):
            lease = authorize(work, data)
            entry = file_info(work, request, data)
            index = entry['index']
            if str(index) in lease['done']:
                return {'verified':True}
            target = uploaded(work, lease, index)
            if not target.is_file() or target.stat().st_size != data.get('size'):
                raise ValueError('Den returnerede fil er ikke færdig.')
            marker = target.with_suffix('.verifying')
            if marker.exists() and time.time() - marker.stat().st_mtime < 2400:
                raise BlockingIOError('Filen bliver allerede kontrolleret.')
            marker.touch()
            report(work,request['id'],'verifying','Kontrollerer filen fra pc’en',95)
        try:
            source = checked(work.parent / entry['name'])
            if entry['video']:
                original = probe(source)
                restore_flags(original, target)
                validate(original, probe(target))
            elif target.stat().st_size != entry['size'] or digest(source) != digest(target):
                raise ValueError('En ledsagefil blev ændret.')
            with locked(work):
                lease = authorize(work, data)
                lease['done'][str(index)] = target.stat().st_size
                save_lease(work, lease)
            return {'verified':True}
        finally:
            marker.unlink(missing_ok=True)
    with locked(work):
        lease = authorize(work, data)
        if action == 'renew':
            lease['expires'] = time.time() + TTL
            save_lease(work, lease)
            if read(work / 'status.json',{}).get('state')=='ready':
                return {'renewed':True}
            phase = data.get('phase')
            messages = {'download':'Sender originalen til pc’en','encode':'GPU-konvertering på pc’en',
                        'upload':'Modtager den konverterede fil fra pc’en','verify':'Kontrollerer filen fra pc’en'}
            if phase in messages:
                progress = data.get('progress',0)
                if type(progress) not in (int,float) or not 0 <= progress <= 100:
                    raise ValueError('Ugyldig fremdrift.')
                report(work,request['id'],'remote',messages[phase],min(99,progress))
            return {'renewed':True}
        if action == 'fail':
            if read(work / 'status.json',{}).get('state')=='ready':
                return {'failed':False}
            lease['expires'] = 0
            save_lease(work, lease)
            report(work,request['id'],'error','Pc-konvertering fejlede. Originalen beholdes. Prøv igen fra downloadens detaljer.')
            return {'failed':True}
        if action == 'complete':
            if read(work / 'status.json',{}).get('state')=='ready':
                return {'complete':True}
            files = manifest(work, request)
            if any(str(f['index']) not in lease['done'] for f in files):
                raise ValueError('Alle filer skal være returneret og kontrolleret først.')
            result = checked(work / 'result')
            result.mkdir(exist_ok=True)
            for f in files:
                source = uploaded(work, lease, f['index'])
                target = checked(result / f['output'])
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if source.exists() or target.stat().st_size != lease['done'][str(f['index'])]:
                        raise ValueError('Resultatfilen findes allerede.')
                else:
                    source.rename(target)
            atomic(result / '.fjordseed-converted.json',json.dumps({'id':request['id'],'files':[f['output'] for f in files]}),mode=0o644)
            report(work,request['id'],'ready','Pc-konvertering kontrolleret · klar til biblioteket',100)
            return {'complete':True}
        entry = file_info(work, request, data)
        if action == 'read':
            offset = data.get('offset'); size = data.get('size')
            if type(offset) is not int or type(size) is not int or not 0 <= offset <= entry['size'] or not 1 <= size <= CHUNK:
                raise ValueError('Ugyldigt filinterval.')
            with checked(work.parent / entry['name']).open('rb') as handle:
                handle.seek(offset)
                return handle.read(min(size,entry['size']-offset))
        if action in ('prepare_upload','append'):
            if str(entry['index']) in lease['done']:
                raise ValueError('Filen er allerede godkendt.')
            target = uploaded(work,lease,entry['index'])
            if target.with_suffix('.verifying').exists():
                raise ValueError('Filen bliver kontrolleret.')
            offset = data.get('offset'); size = data.get('size')
            if type(offset) is not int or type(size) is not int or offset < 0 or not 0 <= size <= CHUNK:
                raise ValueError('Ugyldigt filinterval.')
            if offset+size > max(entry['size']*4,1024**3) + 1024**3:
                raise ValueError('Den returnerede fil er for stor.')
            part = data.get('part','')
            if not re.fullmatch('[a-f0-9]{32}',part):
                raise ValueError('Ugyldig upload.')
            incoming = checked(private(work,lease) / 'incoming')
            if action == 'prepare_upload':
                return {'directory':str(incoming),'name':part}
            chunk = checked(incoming / part)
            if chunk.stat().st_size != size or digest(chunk) != data.get('sha256'):
                raise ValueError('Filoverførslen kunne ikke kontrolleres.')
            current = target.stat().st_size if target.exists() else 0
            try:
                if offset == current:
                    with target.open('ab') as out, chunk.open('rb') as src:
                        shutil.copyfileobj(src,out,CHUNK)
                        out.flush();os.fsync(out.fileno())
                elif offset+size <= current:
                    with target.open('rb') as out:
                        out.seek(offset)
                        if hashlib.sha256(out.read(size)).hexdigest()!=data.get('sha256'):
                            raise ValueError('Uploadintervallet matcher ikke den tidligere fil.')
                else:
                    raise ValueError('Uploadintervallet er ikke det næste i filen.')
            finally:
                chunk.unlink(missing_ok=True)
            return {'offset':target.stat().st_size}
        raise ValueError('Ukendt handling.')


if __name__ == '__main__':
    try:
        ident = sys.argv[1]
        if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('Ugyldig forespørgsel.')
        path = Path('/rpc') / ('remote-' + ident + '.json')
        data = json.loads(path.read_text())
        result = dispatch(data)
        if isinstance(result,bytes):
            sys.stdout.buffer.write(result)
        else:
            print(json.dumps({'ok':True,'data':result}))
    except Exception as exc:
        print(json.dumps({'ok':False,'busy':isinstance(exc,BlockingIOError),
            'error':str(exc) if isinstance(exc,ValueError) else 'Jobbet kunne ikke behandles. Prøv igen.'}))
        raise SystemExit(1)
